from django.test import TestCase

from apps.core.testing import ProjectFixtureMixin, make_issue
from apps.issues import services as issue_services
from apps.issues.models import IssueLink, IssueType
from apps.testmgmt import services
from apps.testmgmt.models import RunStatus, TestPlan


class TestManagementTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.story = make_issue(self.project, self.pm, title="Login")
        self.uncovered = make_issue(self.project, self.pm, title="Logout")
        self.t1 = make_issue(self.project, self.tester, issue_type=IssueType.TEST, title="Login ok")
        self.t2 = make_issue(self.project, self.tester, issue_type=IssueType.TEST, title="Login wrong password")
        for t in (self.t1, self.t2):
            issue_services.link_issues(t, self.story, IssueLink.LinkType.TESTS, self.tester)
        self.plan = TestPlan.objects.create(project=self.project, name="Regression", created_by=self.tester)
        self.plan.tests.set([self.t1, self.t2])

    def test_execution_from_plan_creates_runs(self):
        ex = services.create_execution(self.project, self.tester, name="Run 1", plan=self.plan)
        self.assertEqual(ex.runs.count(), 2)
        self.assertEqual(ex.summary()["todo"], 2)

    def test_coverage_states(self):
        report = services.coverage_report(self.project)
        status = {r["issue"].pk: r["status"] for r in report["rows"]}
        self.assertEqual(status[self.story.pk], services.Coverage.NOT_RUN)
        self.assertEqual(status[self.uncovered.pk], services.Coverage.UNCOVERED)
        self.assertEqual(report["covered_percent"], 50)

        ex = services.create_execution(self.project, self.tester, name="Run 1", plan=self.plan)
        runs = {r.test_id: r for r in ex.runs.all()}
        services.record_result(runs[self.t1.pk], self.tester, RunStatus.PASS)
        services.record_result(runs[self.t2.pk], self.tester, RunStatus.FAIL, "wrong message")
        status = {r["issue"].pk: r["status"] for r in services.coverage_report(self.project)["rows"]}
        self.assertEqual(status[self.story.pk], services.Coverage.NOK)

        # A later execution where both pass makes the requirement OK (latest result wins).
        ex2 = services.create_execution(self.project, self.tester, name="Run 2", plan=self.plan)
        for run in ex2.runs.all():
            services.record_result(run, self.tester, RunStatus.PASS)
        status = {r["issue"].pk: r["status"] for r in services.coverage_report(self.project)["rows"]}
        self.assertEqual(status[self.story.pk], services.Coverage.OK)

    def test_record_result_via_html_and_permissions(self):
        ex = services.create_execution(self.project, self.tester, name="Run", plan=self.plan)
        run = ex.runs.first()
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(f"/projects/TST/tests/runs/{run.pk}/", {"status": "pass"}).status_code, 403)
        self.client.force_login(self.tester)
        self.client.post(f"/projects/TST/tests/runs/{run.pk}/", {"status": "blocked", "comment": "env down"})
        run.refresh_from_db()
        self.assertEqual(run.status, RunStatus.BLOCKED)
        self.assertEqual(run.executed_by, self.tester)

    def test_pages_render(self):
        ex = services.create_execution(self.project, self.tester, name="Run", plan=self.plan)
        self.client.force_login(self.dev)
        for url in (
            "/projects/TST/tests/plans/",
            f"/projects/TST/tests/plans/{self.plan.pk}/",
            "/projects/TST/tests/executions/",
            f"/projects/TST/tests/executions/{ex.pk}/",
            "/projects/TST/tests/coverage/",
            self.story.get_absolute_url(),
            self.t1.get_absolute_url(),
        ):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_steps_editor(self):
        self.client.force_login(self.tester)
        data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "0",
            "form-0-action": "Open login",
            "form-0-expected_result": "Form shown",
            "form-1-action": "",
        }
        response = self.client.post(f"/projects/TST/issues/{self.t1.number}/steps/", data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(self.t1.test_steps.values_list("action", "order")), [("Open login", 1)])
