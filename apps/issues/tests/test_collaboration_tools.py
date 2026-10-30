"""Filters shared by the list, CSV export, saved filters, outgoing webhooks, and releases with release notes."""
import datetime

import csv
import hashlib
import hmac
import io
from unittest import mock
from urllib.error import URLError
from urllib.parse import quote

from django.test import TestCase
from django.urls import reverse

from apps.core.testing import ProjectFixtureMixin, make_issue, make_project, make_user
from apps.accounts.models import Role
from apps.issues import webhooks
from apps.issues import services as issue_services
from apps.issues.filters import clean_query
from apps.issues.models import IssueType, SavedFilter, Webhook
from apps.projects.models import ProjectRole, Version
from apps.issues import services as issue_services


def csv_rows(response):
    text = response.content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


class FilterSetTests(ProjectFixtureMixin, TestCase):
    def test_clean_query_keeps_only_known_keys_with_values(self):
        from django.http import QueryDict

        query = QueryDict("type=bug&status=&evil=1&q=login&sort=key")
        self.assertEqual(clean_query(query), {"type": "bug", "q": "login", "sort": "key"})


class CsvExportTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.bug = make_issue(self.project, self.pm, issue_type=IssueType.BUG, title="Crash on save")
        self.story = make_issue(self.project, self.pm, issue_type=IssueType.STORY, title="Login page")
        self.url = reverse("issues:export", args=[self.project.key])

    def test_export_has_a_header_and_every_matching_issue(self):
        self.client.force_login(self.dev)
        rows = csv_rows(self.client.get(self.url))
        self.assertEqual(rows[0][0], "key")
        self.assertEqual({r[2] for r in rows[1:]}, {"Crash on save", "Login page"})

    def test_export_applies_the_list_filters(self):
        self.client.force_login(self.dev)
        rows = csv_rows(self.client.get(self.url, {"type": "bug"}))
        self.assertEqual([r[2] for r in rows[1:]], ["Crash on save"])

    def test_a_cell_that_starts_like_a_formula_is_quoted(self):
        make_issue(self.project, self.pm, title="=HYPERLINK(\"http://evil\")")
        self.client.force_login(self.dev)
        titles = [r[2] for r in csv_rows(self.client.get(self.url))[1:]]
        self.assertIn("'=HYPERLINK(\"http://evil\")", titles)

    def test_outsider_cannot_export(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 404)


class SavedFilterTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.bug = make_issue(self.project, self.pm, issue_type=IssueType.BUG, title="Crash")
        make_issue(self.project, self.pm, issue_type=IssueType.STORY, title="Story")
        self.save_url = reverse("issues:filter_save", args=[self.project.key])
        self.list_url = reverse("issues:list", args=[self.project.key])

    def test_saving_keeps_the_query_and_loading_applies_it(self):
        self.client.force_login(self.dev)
        self.client.post(self.save_url, {"name": "Bugs", "query": "type=bug&junk=1"})
        saved = SavedFilter.objects.get(owner=self.dev, name="Bugs")
        self.assertEqual(saved.query, "type=bug")
        response = self.client.get(self.list_url, {"saved": saved.pk})
        self.assertEqual([i.title for i in response.context["page"].object_list], ["Crash"])

    def test_a_private_filter_is_not_visible_to_others_but_a_shared_one_is(self):
        private = SavedFilter.objects.create(project=self.project, owner=self.dev, name="Mine", query="type=bug")
        shared = SavedFilter.objects.create(project=self.project, owner=self.dev, name="Team", query="type=bug",
                                            shared=True)
        self.client.force_login(self.pm)
        response = self.client.get(self.list_url)
        names = [f.name for f in response.context["saved_filters"]]
        self.assertIn("Team", names)
        self.assertNotIn("Mine", names)
        self.client.get(self.list_url, {"saved": private.pk})  # does not crash, and ignores the private one
        self.assertTrue(shared.shared)

    def test_only_the_owner_deletes_a_saved_filter(self):
        saved = SavedFilter.objects.create(project=self.project, owner=self.dev, name="Mine", query="type=bug",
                                           shared=True)
        url = reverse("issues:filter_delete", args=[self.project.key, saved.pk])
        self.client.force_login(self.pm)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.assertTrue(SavedFilter.objects.filter(pk=saved.pk).exists())
        self.client.force_login(self.dev)
        self.client.post(url)
        self.assertFalse(SavedFilter.objects.filter(pk=saved.pk).exists())

    def test_an_empty_name_is_refused(self):
        self.client.force_login(self.dev)
        self.client.post(self.save_url, {"name": "  ", "query": "type=bug"})
        self.assertFalse(SavedFilter.objects.exists())


class WebhookSafetyTests(TestCase):
    def test_only_https_addresses_are_accepted(self):
        self.assertIsNone(webhooks.address_problem("https://example.com/hook"))
        self.assertIsNotNone(webhooks.address_problem("http://example.com/hook"))
        self.assertIsNotNone(webhooks.address_problem("ftp://example.com/hook"))

    def test_local_and_private_addresses_are_refused(self):
        for url in ["https://localhost/x", "https://127.0.0.1/x", "https://10.0.0.5/x", "https://192.168.1.1/x",
                    "https://169.254.169.254/latest/meta-data", "https://foo.localhost/x"]:
            self.assertIsNotNone(webhooks.address_problem(url), url)

    def test_the_signature_is_the_hmac_of_the_body(self):
        body = b'{"event": "issue.created"}'
        expected = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        self.assertEqual(webhooks.sign("s3cret", body), expected)


class WebhookDeliveryTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.hook = Webhook.objects.create(project=self.project, url="https://hooks.example.com/mpira",
                                           secret="s3cret", events="issue.created,issue.commented")

    def test_creating_an_issue_sends_one_signed_post_after_commit(self):
        with mock.patch.object(webhooks, "send", return_value=True) as send, self.captureOnCommitCallbacks(execute=True):
            issue = make_issue(self.project, self.dev, title="Hooked")
        self.assertEqual(send.call_count, 1)
        hook, event, payload = send.call_args.args
        self.assertEqual(event, "issue.created")
        self.assertEqual(payload["issue"]["key"], issue.key)

    def test_an_event_the_hook_does_not_listen_for_is_not_sent(self):
        self.hook.events = "issue.commented"
        self.hook.save()
        with mock.patch.object(webhooks, "send", return_value=True) as send, self.captureOnCommitCallbacks(execute=True):
            make_issue(self.project, self.dev, title="Quiet")
        send.assert_not_called()

    def test_a_rolled_back_change_is_never_sent(self):
        with mock.patch.object(webhooks, "send", return_value=True) as send:
            try:
                from django.db import transaction
                with transaction.atomic():
                    make_issue(self.project, self.dev, title="Rolled back")
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
        send.assert_not_called()

    def test_a_failing_receiver_is_recorded_and_does_not_fail_the_action(self):
        with mock.patch("apps.issues.webhooks.urllib.request.urlopen", side_effect=URLError("no route")):
            ok = webhooks.send(self.hook, "issue.created", {"x": 1})
        self.hook.refresh_from_db()
        self.assertFalse(ok)
        self.assertIsNone(self.hook.last_status)
        self.assertIn("URLError", self.hook.last_error)

    def test_a_manager_adds_a_hook_and_a_developer_cannot(self):
        url = reverse("issues:webhooks", args=[self.project.key])
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.pm)
        self.client.post(url, {"action": "add", "url": "https://ci.example.com/hook", "events": ["issue.created"]})
        self.assertTrue(Webhook.objects.filter(url="https://ci.example.com/hook", events="issue.created").exists())

    def test_the_settings_page_refuses_a_private_address(self):
        url = reverse("issues:webhooks", args=[self.project.key])
        self.client.force_login(self.pm)
        self.client.post(url, {"action": "add", "url": "https://10.0.0.1/hook", "events": ["issue.created"]})
        self.assertFalse(Webhook.objects.filter(url="https://10.0.0.1/hook").exists())


class ReleaseTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.version = Version.objects.create(project=self.project, name="1.0")
        self.done = make_issue(self.project, self.pm, issue_type=IssueType.BUG, title="Fixed crash")
        self.open = make_issue(self.project, self.pm, issue_type=IssueType.STORY, title="Still planned")
        self.done.fix_versions.add(self.version)
        self.open.fix_versions.add(self.version)
        for step in ["in_progress", "in_review", "done"]:  # the default workflow has no direct To Do → Done move
            issue_services.transition_issue(self.done, self.pm, step)

    def test_the_page_shows_the_progress_of_each_version(self):
        self.client.force_login(self.dev)
        row = self.client.get(reverse("issues:releases", args=[self.project.key])).context["rows"][0]
        self.assertEqual((row["done"], row["total"], row["percent"]), (1, 2, 50))

    def test_a_version_without_issues_shows_a_dash_instead_of_zero_of_zero(self):
        Version.objects.create(project=self.project, name="2.0")
        self.client.force_login(self.dev)
        response = self.client.get(reverse("issues:releases", args=[self.project.key]))
        self.assertContains(response, "1/2 (50%)")  # version 1.0 keeps its progress
        self.assertNotContains(response, "0/0")

    def test_the_notes_list_finished_work_by_type_and_the_rest_separately(self):
        self.client.force_login(self.dev)
        url = reverse("issues:release_notes", args=[self.project.key, self.version.pk])
        text = self.client.get(url).content.decode("utf-8")
        self.assertIn(f"- {self.done.key} Fixed crash", text)
        self.assertIn("Not done", text)
        self.assertIn(f"- {self.open.key} Still planned", text)

    def test_the_notes_can_be_downloaded_as_markdown(self):
        self.client.force_login(self.dev)
        url = reverse("issues:release_notes", args=[self.project.key, self.version.pk])
        response = self.client.get(url, {"download": 1})
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(response["Content-Type"].startswith("text/markdown"))

    def test_a_greek_version_name_survives_the_download_header(self):
        self.version.name = "Έκδοση 2"
        self.version.save()
        self.client.force_login(self.dev)
        url = reverse("issues:release_notes", args=[self.project.key, self.version.pk])
        header = self.client.get(url, {"download": 1})["Content-Disposition"]
        self.assertNotIn("=?", header)  # no RFC 2047 encoded word: browsers do not decode those in file names
        self.assertIn("filename*=UTF-8''" + quote(f"{self.project.key}-Έκδοση 2.md"), header)


class BulkActionTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.a = make_issue(self.project, self.pm, title="First")
        self.b = make_issue(self.project, self.pm, title="Second")
        self.url = reverse("issues:bulk", args=[self.project.key])

    def post(self, user, action, value="", numbers=None):
        self.client.force_login(user)
        return self.client.post(self.url, {
            "action": action, "value": value,
            "issues": numbers if numbers is not None else [self.a.number, self.b.number],
        })

    def test_a_manager_moves_several_issues_to_a_status(self):
        self.post(self.pm, "transition", "in_progress")
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.assertEqual((self.a.status, self.b.status), ("in_progress", "in_progress"))

    def test_the_result_message_is_singular_for_one_issue_and_plural_for_more(self):
        self.client.force_login(self.pm)
        one = self.client.post(self.url, {"action": "transition", "value": "in_progress", "issues": [self.a.number]}, follow=True)
        self.assertContains(one, "1 issue changed.")
        both = self.client.post(self.url, {"action": "assign", "value": str(self.dev.pk), "issues": [self.a.number, self.b.number]}, follow=True)
        self.assertContains(both, "2 issues changed.")

    def test_an_illegal_move_is_reported_and_the_others_still_change(self):
        self.post(self.pm, "transition", "in_progress")
        self.post(self.pm, "transition", "done")  # To Do → Done is not allowed, but In Progress → Done is
        self.a.refresh_from_db()
        self.assertEqual(self.a.status, "in_progress")

    def test_assigning_to_a_non_member_is_refused(self):
        self.post(self.pm, "assign", str(self.outsider.pk))
        self.a.refresh_from_db()
        self.assertIsNone(self.a.assignee)

    def test_assign_to_a_member_and_set_priority(self):
        self.post(self.pm, "assign", str(self.dev.pk))
        self.post(self.pm, "priority", "high")
        self.a.refresh_from_db()
        self.assertEqual((self.a.assignee, self.a.priority), (self.dev, "high"))

    def test_a_developer_cannot_delete_in_bulk(self):
        self.post(self.dev, "delete")
        self.assertTrue(self.project.issues.filter(pk=self.a.pk).exists())

    def test_a_manager_deletes_in_bulk(self):
        self.post(self.pm, "delete")
        self.assertFalse(self.project.issues.filter(pk__in=[self.a.pk, self.b.pk]).exists())

    def test_numbers_of_another_project_are_ignored(self):
        other = make_project("OTH", members=[(self.pm, ProjectRole.PROJECT_MANAGER)])
        foreign = make_issue(other, self.pm, title="Elsewhere")
        self.post(self.pm, "priority", "high", numbers=[foreign.number])
        foreign.refresh_from_db()
        self.assertEqual(foreign.priority, "medium")

    def test_a_viewer_cannot_use_bulk_actions(self):
        self.client.force_login(self.viewer)
        response = self.client.post(self.url, {"action": "priority", "value": "high", "issues": [self.a.number]})
        self.assertEqual(response.status_code, 403)  # a member without the capability gets 403, not 404
        self.a.refresh_from_db()
        self.assertEqual(self.a.priority, "medium")


class QueryLanguageTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.bug = make_issue(self.project, self.dev, issue_type=IssueType.BUG, title="Login crash",
                              priority="high")
        self.bug.assignee = self.dev
        self.bug.save()
        self.story = make_issue(self.project, self.pm, issue_type=IssueType.STORY, title="Checkout flow")
        self.done = make_issue(self.project, self.pm, issue_type=IssueType.TASK, title="Old task")
        for step in ["in_progress", "in_review", "done"]:
            issue_services.transition_issue(self.done, self.pm, step)

    def titles(self, jql, user=None):
        from apps.issues.filters import apply_jql

        qs = apply_jql(self.project.issues.all(), jql, self.project, user or self.pm)
        return sorted(i.title for i in qs)

    def test_type_and_status_and_negation(self):
        self.assertEqual(self.titles("type = bug"), ["Login crash"])
        self.assertEqual(self.titles("status != done"), ["Checkout flow", "Login crash"])

    def test_current_user_and_text_search(self):
        self.assertEqual(self.titles("assignee = currentUser()", user=self.dev), ["Login crash"])
        self.assertEqual(self.titles('title ~ "checkout"'), ["Checkout flow"])

    def test_or_with_parentheses_and_in_lists(self):
        self.assertEqual(self.titles("(type = bug OR type = task) AND status = done"), ["Old task"])
        self.assertEqual(self.titles("priority IN (high, highest)"), ["Login crash"])
        self.assertEqual(self.titles("priority NOT IN (high, highest)"), ["Checkout flow", "Old task"])

    def test_empty_checks(self):
        self.assertEqual(self.titles("assignee IS EMPTY"), ["Checkout flow", "Old task"])
        self.assertEqual(self.titles("assignee IS NOT EMPTY"), ["Login crash"])

    def test_order_by_changes_the_order(self):
        from apps.issues.filters import apply_jql

        qs = apply_jql(self.project.issues.all(), "ORDER BY title DESC", self.project, self.pm)
        self.assertEqual([i.title for i in qs], ["Old task", "Login crash", "Checkout flow"])

    def test_mistakes_are_reported_in_words(self):
        from apps.issues.query import QueryError, parse

        for bad, fragment in [("colour = red", "Unknown field"), ("type = spaceship", "Unknown type"),
                              ("priority = urgent", "Unknown priority"), ("created > yesterday", "not a date"),
                              ("title = x", "supports ~"), ("(type = bug", "Expected")]:
            with self.assertRaises(QueryError) as ctx:
                parse(bad, self.project, self.pm)
            self.assertIn(fragment, str(ctx.exception), bad)

    def test_a_bad_query_on_the_list_page_shows_a_message_and_keeps_the_list(self):
        self.client.force_login(self.dev)
        response = self.client.get(reverse("issues:list", args=[self.project.key]), {"jql": "colour = red"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page"].paginator.count, 3)


class InlineEditTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.issue = make_issue(self.project, self.pm, title="Row to edit")
        self.url = reverse("issues:inline", args=[self.project.key, self.issue.number])

    def test_a_row_change_is_saved_and_recorded(self):
        self.client.force_login(self.dev)
        response = self.client.post(self.url, {"field": "priority", "value": "high"})
        self.assertEqual(response.status_code, 200)
        self.issue.refresh_from_db()
        self.assertEqual(self.issue.priority, "high")
        self.assertTrue(self.issue.activity.filter(field="priority", new_value="high").exists())

    def test_a_refused_change_answers_400_with_the_reason(self):
        self.client.force_login(self.dev)
        response = self.client.post(self.url, {"field": "status", "value": "done"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Cannot move", response.json()["error"])

    def test_a_viewer_cannot_change_rows(self):
        self.client.force_login(self.viewer)
        response = self.client.post(self.url, {"field": "priority", "value": "high"})
        self.assertEqual(response.status_code, 403)


class TimelineTests(ProjectFixtureMixin, TestCase):
    def test_dated_issues_are_bars_and_undated_ones_are_counted(self):
        import datetime

        dated = make_issue(self.project, self.pm, title="Dated", start_date=datetime.date(2026, 10, 1),
                           due_date=datetime.date(2026, 10, 10))
        make_issue(self.project, self.pm, title="No dates")
        self.client.force_login(self.dev)
        response = self.client.get(reverse("issues:timeline", args=[self.project.key]), {"group": "assignee"})
        lanes = response.context["lanes"]
        titles = [row["issue"].title for lane in lanes for row in lane["rows"]]
        self.assertEqual(titles, [dated.title])
        self.assertEqual(response.context["undated"], 1)
        self.assertEqual(lanes[0]["rows"][0]["left"], 0.0)


class AutomationTests(ProjectFixtureMixin, TestCase):
    def rule(self, **fields):
        from apps.issues.models import Rule

        values = {"project": self.project, "name": "rule", "trigger": Rule.Trigger.CREATED,
                  "action": Rule.Action.SET_PRIORITY, "value": "high"}
        values.update(fields)
        return Rule.objects.create(**values)

    def test_a_matching_rule_acts_on_the_new_issue(self):
        self.rule(condition="type = bug")
        bug = make_issue(self.project, self.dev, issue_type=IssueType.BUG, title="Crash")
        story = make_issue(self.project, self.dev, issue_type=IssueType.STORY, title="Plain")
        bug.refresh_from_db()
        story.refresh_from_db()
        self.assertEqual(bug.priority, "high")
        self.assertEqual(story.priority, "medium")

    def test_a_disabled_rule_does_nothing(self):
        self.rule(enabled=False)
        issue = make_issue(self.project, self.dev, title="Quiet")
        issue.refresh_from_db()
        self.assertEqual(issue.priority, "medium")

    def test_a_comment_rule_fires_on_a_transition_and_does_not_loop(self):
        from apps.issues.models import Comment, Rule

        self.rule(trigger=Rule.Trigger.TRANSITIONED, action=Rule.Action.COMMENT, value="Moved on")
        self.rule(name="loop", trigger=Rule.Trigger.COMMENTED, action=Rule.Action.COMMENT, value="echo")
        issue = make_issue(self.project, self.pm, title="Flow")
        issue_services.transition_issue(issue, self.pm, "in_progress")
        self.assertEqual(Comment.objects.filter(issue=issue, body="Moved on").count(), 1)
        self.assertEqual(Comment.objects.filter(issue=issue, body="echo").count(), 0)

    def test_a_failing_rule_records_its_error_and_the_change_still_happens(self):
        from apps.issues.models import Rule

        bad = self.rule(name="bad", trigger=Rule.Trigger.CREATED, action=Rule.Action.SET_STATUS, value="done")
        issue = make_issue(self.project, self.pm, title="Survives")
        bad.refresh_from_db()
        self.assertTrue(bad.last_error)
        self.assertTrue(self.project.issues.filter(pk=issue.pk).exists())

    def test_a_rule_with_a_bad_query_is_refused_on_the_settings_page(self):
        from apps.issues.models import Rule

        url = reverse("issues:automation", args=[self.project.key])
        self.client.force_login(self.pm)
        self.client.post(url, {"action": "add", "name": "x", "trigger": Rule.Trigger.CREATED,
                               "condition": "colour = red", "rule_action": Rule.Action.COMMENT, "value": "hi"})
        self.assertFalse(Rule.objects.filter(name="x").exists())

    def test_only_managers_see_the_rules_page(self):
        url = reverse("issues:automation", args=[self.project.key])
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.pm)
        self.assertEqual(self.client.get(url).status_code, 200)


class DailyRuleTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        from apps.issues.models import Rule

        self.Rule = Rule
        self.old = make_issue(self.project, self.pm, title="Overdue")
        self.old.due_date = datetime.date(2026, 1, 1)
        self.old.save()
        self.new = make_issue(self.project, self.pm, title="Later")
        self.new.due_date = datetime.date(2030, 1, 1)
        self.new.save()

    def test_a_daily_rule_changes_only_the_matching_issues(self):
        from apps.issues.automation import run_scheduled

        rule = self.Rule.objects.create(project=self.project, name="Overdue to high", created_by=self.pm,
                                        trigger=self.Rule.Trigger.SCHEDULED, condition="duedate < 2026-06-01",
                                        action=self.Rule.Action.SET_PRIORITY, value="high")
        self.assertEqual(run_scheduled(rule), 1)
        self.old.refresh_from_db()
        self.new.refresh_from_db()
        self.assertEqual((self.old.priority, self.new.priority), ("high", "medium"))

    def test_the_command_runs_enabled_daily_rules_only(self):
        from io import StringIO
        from django.core.management import call_command

        self.Rule.objects.create(project=self.project, name="On", created_by=self.pm,
                                 trigger=self.Rule.Trigger.SCHEDULED, condition="duedate < 2026-06-01",
                                 action=self.Rule.Action.SET_PRIORITY, value="low")
        self.Rule.objects.create(project=self.project, name="Off", created_by=self.pm, enabled=False,
                                 trigger=self.Rule.Trigger.SCHEDULED, condition="duedate < 2026-06-01",
                                 action=self.Rule.Action.SET_PRIORITY, value="high")
        out = StringIO()
        call_command("run_rules", stdout=out)
        self.assertIn("1 rules run", out.getvalue())
        self.old.refresh_from_db()
        self.assertEqual(self.old.priority, "low")

    def test_a_daily_rule_without_condition_or_with_a_comment_is_refused(self):
        from apps.issues.automation import validate

        self.assertIn("needs a condition", validate(self.project, self.Rule.Trigger.SCHEDULED, "",
                                                    self.Rule.Action.SET_PRIORITY, "high", self.pm))
        self.assertIn("cannot add comments", validate(self.project, self.Rule.Trigger.SCHEDULED, "type = bug",
                                                      self.Rule.Action.COMMENT, "hi", self.pm))


class ApiQueryAndBoardTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.bug = make_issue(self.project, self.pm, issue_type=IssueType.BUG, title="Api bug")
        make_issue(self.project, self.pm, issue_type=IssueType.STORY, title="Api story")

    def test_the_rest_search_takes_a_query_with_a_project(self):
        from rest_framework.test import APIClient

        api = APIClient()
        api.force_authenticate(self.dev)
        response = api.get("/api/v1/issues/", {"project": "TST", "jql": "type = bug"})
        self.assertEqual(response.status_code, 200)
        titles = [i["title"] for i in response.json()["results"]] if isinstance(response.json(), dict) else [i["title"] for i in response.json()]
        self.assertEqual(titles, ["Api bug"])

    def test_a_query_without_a_project_is_refused(self):
        from rest_framework.test import APIClient

        api = APIClient()
        api.force_authenticate(self.dev)
        self.assertEqual(api.get("/api/v1/issues/", {"jql": "type = bug"}).status_code, 400)

    def test_a_card_offers_an_assignee_picker_to_editors(self):
        issue = make_issue(self.project, self.pm, title="Pick me")
        self.client.force_login(self.pm)
        response = self.client.get(reverse("agile:board", args=[self.project.key]), {"scope": "all"})
        self.assertContains(response, 'class="card-assignee"')
        self.assertContains(response, reverse("issues:inline", args=[self.project.key, issue.number]))

    def test_the_assignee_picker_saves_the_change(self):
        issue = make_issue(self.project, self.pm, title="Reassign me")
        self.client.force_login(self.pm)
        response = self.client.post(reverse("issues:inline", args=[self.project.key, issue.number]),
                                    {"field": "assignee", "value": str(self.dev.pk)})
        self.assertEqual(response.status_code, 200)
        issue.refresh_from_db()
        self.assertEqual(issue.assignee, self.dev)

    def test_the_issue_page_offers_the_assignee_picker_to_editors(self):
        issue = make_issue(self.project, self.pm, title="Open me")
        self.client.force_login(self.pm)
        response = self.client.get(reverse("issues:detail", args=[self.project.key, issue.number]))
        self.assertContains(response, 'data-field="assignee"')
        self.assertContains(response, reverse("issues:inline", args=[self.project.key, issue.number]))
        self.assertContains(response, f'<option value="{self.dev.pk}"')

    def test_the_issue_page_shows_the_assignee_as_text_to_viewers(self):
        issue = make_issue(self.project, self.pm, title="Read only")
        self.client.force_login(self.viewer)
        response = self.client.get(reverse("issues:detail", args=[self.project.key, issue.number]))
        self.assertNotContains(response, 'data-field="assignee"')

    def test_the_board_splits_into_one_board_per_swimlane(self):
        self.client.force_login(self.dev)
        response = self.client.get(reverse("agile:board", args=[self.project.key]), {"scope": "all", "swimlane": "assignee"})
        self.assertEqual(response.status_code, 200)
        names = [lane["name"] for lane in response.context["lanes"]]
        self.assertEqual(names, ["Unassigned"])
        self.assertContains(response, 'data-board', count=1)

    def test_the_board_puts_each_epic_in_its_own_swimlane(self):
        epic = make_issue(self.project, self.pm, issue_type=IssueType.EPIC, title="Checkout")
        make_issue(self.project, self.pm, title="Pay button", epic=epic)
        make_issue(self.project, self.pm, title="Loose task")
        self.client.force_login(self.dev)
        response = self.client.get(reverse("agile:board", args=[self.project.key]), {"scope": "all", "swimlane": "epic"})
        names = [lane["name"] for lane in response.context["lanes"]]
        self.assertEqual(names, [f"{epic.key} Checkout", "No epic"])  # named lanes first, "No epic" last
        self.assertContains(response, 'data-board', count=2)


class NavigationTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.releases = reverse("issues:releases", args=[self.project.key])
        self.timeline = reverse("issues:timeline", args=[self.project.key])
        self.webhooks = reverse("issues:webhooks", args=[self.project.key])
        self.automation = reverse("issues:automation", args=[self.project.key])

    def test_every_member_sees_releases_and_timeline_in_the_sidebar(self):
        self.client.force_login(self.dev)
        page = self.client.get(self.releases)
        self.assertContains(page, self.timeline)
        self.assertContains(page, self.releases)

    def test_webhooks_and_automation_are_listed_only_for_managers(self):
        self.client.force_login(self.dev)
        page = self.client.get(self.releases)
        self.assertNotContains(page, self.webhooks)
        self.assertNotContains(page, self.automation)
        self.client.force_login(self.pm)
        page = self.client.get(self.releases)
        self.assertContains(page, self.webhooks)
        self.assertContains(page, self.automation)

    def test_the_favicon_is_served_without_login(self):
        response = self.client.get("/favicon.ico")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/svg+xml")


class AutomationFormTests(ProjectFixtureMixin, TestCase):
    def test_a_valid_rule_is_created_from_the_form(self):
        from apps.issues.models import Rule

        url = reverse("issues:automation", args=[self.project.key])
        self.client.force_login(self.pm)
        self.client.post(url, {"action": "add", "name": "Comment on bugs", "trigger": Rule.Trigger.CREATED,
                               "condition": "type = bug", "rule_action": Rule.Action.COMMENT, "value": "Seen"})
        rule = Rule.objects.get(name="Comment on bugs")
        self.assertEqual((rule.action, rule.value, rule.created_by), (Rule.Action.COMMENT, "Seen", self.pm))
