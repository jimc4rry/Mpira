"""Runs the project's automation rules after a change.

Rules run in the same transaction as the change that triggered them. Each rule has its own savepoint: a rule that fails
records its error on itself and the others, and the user's change, still happen. A change made by a rule does not start
other rules, so two rules cannot loop.
"""

import logging
import threading

from django.db import transaction

from . import bulk, services
from .filters import apply_jql
from .models import Issue, Rule
from .query import QueryError


logger = logging.getLogger(__name__)
_state = threading.local()


def condition_matches(rule, issue, user):
    if not rule.condition.strip():
        return True
    return apply_jql(Issue.objects.filter(pk=issue.pk), rule.condition, issue.project, user).exists()


def apply_action(rule, issue, user):
    if rule.action == Rule.Action.SET_STATUS:
        services.transition_issue(issue, user, rule.value)
    elif rule.action == Rule.Action.SET_PRIORITY:
        _, failed = bulk.bulk_apply(issue.project, user, [issue], "priority", rule.value)
        if failed:
            raise bulk.BulkError(failed[0][1])
    elif rule.action == Rule.Action.ASSIGN:
        _, failed = bulk.bulk_apply(issue.project, user, [issue], "assign", rule.value)
        if failed:
            raise bulk.BulkError(failed[0][1])
    elif rule.action == Rule.Action.COMMENT:
        services.add_comment(issue, user, rule.value)


def run(issue, trigger, user):
    """Called by the services after a change. Does nothing while a rule is already running."""
    if getattr(_state, "active", False):
        return
    rules = list(issue.project.automation_rules.filter(enabled=True, trigger=trigger).order_by("id"))
    if not rules:
        return
    _state.active = True
    try:
        for rule in rules:
            try:
                with transaction.atomic():
                    if condition_matches(rule, issue, user):
                        apply_action(rule, issue, user)
                error = ""
            except Exception as exc:  # one rule never stops the rest
                error = f"{type(exc).__name__}: {exc}"[:200]
                logger.warning("automation rule %s failed on %s: %s", rule.pk, issue.key, error)
            if error != rule.last_error:
                rule.last_error = error
                rule.save(update_fields=["last_error"])
    finally:
        _state.active = False


def run_scheduled(rule):
    """Applies a daily rule to every issue its condition matches, as the rule's creator.

    The action runs for every matching issue on every run, so only actions that do the same thing again are allowed
    here (no comments). Returns how many issues were changed.
    """
    actor = rule.created_by
    if actor is None:
        raise bulk.BulkError("The rule has no creator to act as.")
    issues = apply_jql(Issue.objects.filter(project=rule.project), rule.condition, rule.project, actor)
    changed = 0
    _state.active = True
    try:
        for issue in issues:
            try:
                with transaction.atomic():
                    apply_action(rule, issue, actor)
                changed += 1
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"[:200]
                logger.warning("scheduled rule %s failed on %s: %s", rule.pk, issue.key, error)
                rule.last_error = error
    finally:
        _state.active = False
    rule.save(update_fields=["last_error"])
    return changed


def validate(project, trigger, condition, action, value, user):
    """Checks a rule before it is saved. Returns a message for the user, or None when it is fine."""
    from .query import parse

    if trigger not in Rule.Trigger.values or action not in Rule.Action.values:
        return "Choose when and what the rule does."
    if condition.strip():
        try:
            parse(condition, project, user)
        except QueryError as exc:
            return str(exc)
    if action == Rule.Action.COMMENT and not value.strip():
        return "A comment needs text."
    if trigger == Rule.Trigger.SCHEDULED:
        if not condition.strip():
            return "A daily rule needs a condition, so it knows which issues to change."
        if action == Rule.Action.COMMENT:
            return "A daily rule cannot add comments: it would repeat every day."
    if action == Rule.Action.SET_STATUS:
        from . import workflow

        if value not in workflow.status_map(project):
            return "Choose a status."
    if action in (Rule.Action.SET_PRIORITY, Rule.Action.ASSIGN):
        try:
            bulk._check_value(project, "priority" if action == Rule.Action.SET_PRIORITY else "assign", value)
        except bulk.BulkError as exc:
            return str(exc)
    return None
