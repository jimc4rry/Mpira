import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.agile.models import Sprint
from apps.core.testing import ProjectFixtureMixin, make_issue
from apps.issues.models import CustomFieldDefinition, Issue, IssueType, Status
from apps.testmgmt import services as test_services
from apps.testmgmt.models import TestPlan


class ApiTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.api = APIClient()
        self.api.force_authenticate(self.dev)

    def test_unauthenticated_gets_uniform_error(self):
        response = APIClient().get("/api/v1/projects/")
        self.assertIn(response.status_code, (401, 403))
        self.assertIn("error", response.json())

    def test_issue_crud(self):
        response = self.api.post(
            "/api/v1/projects/TST/issues/",
            {"title": "From API", "issue_type": "story", "story_points": 5, "assignee": self.dev.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["key"], "TST-1")
        number = response.json()["number"]

        response = self.api.patch(f"/api/v1/projects/TST/issues/{number}/", {"priority": "high"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["priority"], "high")
        self.assertTrue(Issue.objects.get(number=number).activity.filter(field="priority").exists())

        listing = self.api.get("/api/v1/projects/TST/issues/?type=story").json()
        self.assertEqual(listing["count"], 1)

        self.assertEqual(self.api.delete(f"/api/v1/projects/TST/issues/{number}/").status_code, 403)
        self.api.force_authenticate(self.pm)
        self.assertEqual(self.api.delete(f"/api/v1/projects/TST/issues/{number}/").status_code, 204)

    def test_status_is_read_only_on_patch(self):
        issue = make_issue(self.project, self.dev)
        self.api.patch(f"/api/v1/projects/TST/issues/{issue.number}/", {"status": "done"}, format="json")
        issue.refresh_from_db()
        self.assertEqual(issue.status, Status.TODO)

    def test_validation_errors_have_details(self):
        CustomFieldDefinition.objects.create(project=self.project, name="Impact", key="impact", field_type="select", options="Low,High")
        response = self.api.post(
            "/api/v1/projects/TST/issues/",
            {"title": "x", "issue_type": "subtask", "custom_fields": {"impact": "Huge", "unknown": 1}},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        body = response.json()["error"]
        self.assertEqual(body["code"], "validation_error")
        self.assertIn("parent", body["details"])

        response = self.api.post(
            "/api/v1/projects/TST/issues/", {"title": "x", "custom_fields": {"impact": "Huge", "unknown": 1}}, format="json"
        )
        details = response.json()["error"]["details"]["custom_fields"]
        self.assertIn("impact", details)
        self.assertIn("unknown", details)

    def test_assignee_must_be_member(self):
        response = self.api.post("/api/v1/projects/TST/issues/", {"title": "x", "assignee": self.outsider.pk}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_non_member_gets_404(self):
        self.api.force_authenticate(self.outsider)
        response = self.api.get("/api/v1/projects/TST/issues/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_viewer_cannot_write(self):
        self.api.force_authenticate(self.viewer)
        response = self.api.post("/api/v1/projects/TST/issues/", {"title": "x"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "permission_denied")

    def test_transition_and_workflow_conflict(self):
        issue = make_issue(self.project, self.dev)
        url = f"/api/v1/projects/TST/issues/{issue.number}/transition/"
        response = self.api.post(url, {"status": "done"}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "conflict")
        self.assertEqual(self.api.post(url, {"status": "in_progress"}, format="json").json()["status"], "in_progress")

    def test_board_move_with_rank_and_backlog_move_into_sprint(self):
        a = make_issue(self.project, self.dev)
        b = make_issue(self.project, self.dev)
        c = make_issue(self.project, self.dev)
        # Drop c between a and b in the In Progress column.
        response = self.api.post(
            f"/api/v1/projects/TST/issues/{c.number}/move/",
            {"status": "in_progress", "before": a.number, "after": b.number},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        c.refresh_from_db()
        self.assertTrue(a.rank < c.rank < b.rank)
        self.assertEqual(c.status, Status.IN_PROGRESS)

        sprint = Sprint.objects.create(project=self.project, name="S")
        self.api.post(f"/api/v1/projects/TST/issues/{a.number}/move/", {"sprint": sprint.pk}, format="json")
        a.refresh_from_db()
        self.assertEqual(a.sprint, sprint)
        self.api.post(f"/api/v1/projects/TST/issues/{a.number}/move/", {"sprint": None}, format="json")
        a.refresh_from_db()
        self.assertIsNone(a.sprint)

    def test_sprint_lifecycle_via_api(self):
        self.api.force_authenticate(self.pm)
        sprint_id = self.api.post("/api/v1/projects/TST/sprints/", {"name": "API sprint"}, format="json").json()["id"]
        issue = make_issue(self.project, self.pm, story_points=3, sprint=Sprint.objects.get(pk=sprint_id))
        today = timezone.localdate()
        response = self.api.post(
            f"/api/v1/projects/TST/sprints/{sprint_id}/start/",
            {"start_date": today.isoformat(), "end_date": (today + datetime.timedelta(days=7)).isoformat()},
            format="json",
        )
        self.assertEqual(response.json()["state"], "active")
        self.assertEqual(response.json()["committed_points"], 3)
        burn = self.api.get(f"/api/v1/projects/TST/sprints/{sprint_id}/burndown/").json()
        self.assertEqual(burn["actual"][0], 3)
        self.assertEqual(self.api.post(f"/api/v1/projects/TST/sprints/{sprint_id}/start/", {}, format="json").status_code, 409)
        response = self.api.post(f"/api/v1/projects/TST/sprints/{sprint_id}/complete/", {}, format="json")
        self.assertEqual(response.json()["moved_issues"], 1)
        issue.refresh_from_db()
        self.assertIsNone(issue.sprint)

    def test_dev_cannot_manage_sprints(self):
        response = self.api.post("/api/v1/projects/TST/sprints/", {"name": "nope"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_comments_and_test_runs(self):
        issue = make_issue(self.project, self.dev)
        response = self.api.post(f"/api/v1/projects/TST/issues/{issue.number}/comments/", {"body": "hi @qa"}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.api.post(f"/api/v1/projects/TST/issues/{issue.number}/comments/", {"body": "  "}, format="json").status_code, 400)

        test = make_issue(self.project, self.tester, issue_type=IssueType.TEST)
        plan = TestPlan.objects.create(project=self.project, name="P")
        plan.tests.set([test])
        run = test_services.create_execution(self.project, self.tester, name="E", plan=plan).runs.get()
        response = self.api.patch(f"/api/v1/projects/TST/test-runs/{run.pk}/", {"status": "pass"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "pass")
        self.assertEqual(self.api.patch(f"/api/v1/projects/TST/test-runs/{run.pk}/", {"status": "meh"}, format="json").status_code, 400)
        coverage = self.api.get("/api/v1/projects/TST/coverage/").json()
        self.assertIn("covered_percent", coverage)

    def test_markdown_preview(self):
        html = self.api.post("/api/v1/markdown-preview/", {"text": "**hi** <script>x</script>"}, format="json").json()["html"]
        self.assertIn("<strong>hi</strong>", html)
        self.assertNotIn("<script>", html)


class HealthTests(TestCase):
    def test_healthz(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["database"], "ok")


class ProjectMembersApiTests(ProjectFixtureMixin, TestCase):
    def test_project_detail_lists_members_for_tools(self):
        self.api = APIClient()
        self.api.force_authenticate(self.dev)
        data = self.api.get("/api/v1/projects/TST/").json()
        emails = {m["email"] for m in data["members"]}
        self.assertIn(self.pm.email, emails)
        self.assertIn(self.dev.email, emails)
