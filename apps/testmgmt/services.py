from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.issues.models import REQUIREMENT_TYPES, Issue, IssueLink, IssueType

from .models import RunState, RunStatus, TestExecution, TestRun


class Coverage:
    """Requirement coverage states, Xray-style but simplified."""

    UNCOVERED = "uncovered"
    NOT_RUN = "not_run"
    OK = "ok"
    NOK = "nok"
    BLOCKED = "blocked"

    LABELS = {
        UNCOVERED: _("Uncovered"),
        NOT_RUN: _("Not run"),
        OK: _("OK"),
        NOK: _("Failing"),
        BLOCKED: _("Blocked"),
    }


@transaction.atomic
def create_execution(project, user, *, name, plan=None, tests=(), environment="", fix_version=None):
    execution = TestExecution.objects.create(
        project=project,
        plan=plan,
        name=name,
        environment=environment,
        fix_version=fix_version,
        created_by=user,
    )
    test_ids = set(t.pk for t in tests)
    if plan is not None:
        test_ids |= set(plan.tests.values_list("pk", flat=True))
    valid = Issue.objects.filter(pk__in=test_ids, project=project, issue_type=IssueType.TEST)
    TestRun.objects.bulk_create([TestRun(execution=execution, test=t) for t in valid])
    return execution


def record_result(run, user, status, comment=None):
    if status not in RunStatus.values:
        raise ValueError(status)
    run.status = status
    if comment is not None:
        run.comment = comment
    if status == RunStatus.TODO:
        run.executed_by, run.executed_at = None, None
    else:
        run.executed_by, run.executed_at = user, timezone.now()
    run.save()
    return run


def request_automated_run(execution, user):
    """Queue an execution for the automated runner. Only one run at a time."""
    if execution.run_state in (RunState.QUEUED, RunState.RUNNING):
        raise ValueError("Η εκτέλεση είναι ήδη σε εξέλιξη ή στην ουρά.")
    execution.run_state = RunState.QUEUED
    execution.run_requested_by = user
    execution.run_requested_at = timezone.now()
    execution.run_finished_at = None
    execution.save(update_fields=["run_state", "run_requested_by", "run_requested_at", "run_finished_at"])
    return execution


def set_run_state(execution, state):
    if state not in RunState.values:
        raise ValueError(state)
    execution.run_state = state
    if state == RunState.DONE:
        execution.run_finished_at = timezone.now()
    execution.save(update_fields=["run_state", "run_finished_at"])
    return execution


def latest_results(test_ids):
    """{test_id: latest executed TestRun} - the 'current' result of each test."""
    latest = {}
    for run in (
        TestRun.objects.filter(test_id__in=test_ids)
        .exclude(status=RunStatus.TODO)
        .select_related("execution")
        .order_by("executed_at", "id")
    ):
        latest[run.test_id] = run
    return latest


def requirement_status(test_ids, latest):
    if not test_ids:
        return Coverage.UNCOVERED
    statuses = [latest[t].status for t in test_ids if t in latest]
    if RunStatus.FAIL in statuses:
        return Coverage.NOK
    if RunStatus.BLOCKED in statuses:
        return Coverage.BLOCKED
    if len(statuses) < len(test_ids):
        return Coverage.NOT_RUN
    return Coverage.OK


def coverage_report(project, fix_version=None):
    requirements = Issue.objects.filter(project=project, issue_type__in=REQUIREMENT_TYPES).select_related("project")
    if fix_version is not None:
        requirements = requirements.filter(fix_versions=fix_version)
    requirements = list(requirements.order_by("number"))
    links = IssueLink.objects.filter(
        link_type=IssueLink.LinkType.TESTS, target__in=requirements
    ).select_related("source__project")
    tests_by_req = {}
    for link in links:
        tests_by_req.setdefault(link.target_id, []).append(link.source)
    all_test_ids = {t.pk for tests in tests_by_req.values() for t in tests}
    latest = latest_results(all_test_ids)

    rows, totals = [], {k: 0 for k in Coverage.LABELS}
    for req in requirements:
        tests = tests_by_req.get(req.pk, [])
        status = requirement_status([t.pk for t in tests], latest)
        totals[status] += 1
        rows.append(
            {
                "issue": req,
                "tests": [(t, latest.get(t.pk)) for t in tests],
                "status": status,
                "status_label": Coverage.LABELS[status],
            }
        )
    total = len(rows)
    covered = total - totals[Coverage.UNCOVERED]
    return {
        "rows": rows,
        "totals": [
            {"key": k, "label": Coverage.LABELS[k], "count": totals[k], "percent": round(100 * totals[k] / total) if total else 0}
            for k in Coverage.LABELS
        ],
        "total": total,
        "covered_percent": round(100 * covered / total) if total else 0,
    }
