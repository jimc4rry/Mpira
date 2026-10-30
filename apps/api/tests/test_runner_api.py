from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.testing import ProjectFixtureMixin, make_issue
from apps.issues.models import IssueLink, IssueType
from apps.testmgmt import services
from apps.testmgmt.models import RunState, RunStatus, TestPlan


class RunnerApiTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.story = make_issue(self.project, self.pm, title="Login")
        self.test = make_issue(self.project, self.tester, issue_type=IssueType.TEST, title="Login ok",
                               custom_fields={"automation": "auto"})
        self.plan = TestPlan.objects.create(project=self.project, name="Reg", created_by=self.tester)
        self.plan.tests.set([self.test])
        self.api = APIClient()
        self.api.force_authenticate(self.tester)

    def base(self):
        return f"/api/v1/projects/{self.project.key}"

    def test_create_execution_from_plan_and_list_queued(self):
        response = self.api.post(f"{self.base()}/test-executions/",
                                 {"name": "Run 1", "plan": self.plan.pk, "environment": "UAT"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual(data["counts"]["total"], 1)
        self.assertEqual(data["run_state"], "idle")
        listed = self.api.get(f"{self.base()}/test-executions/?state=queued").json()
        self.assertEqual(listed, [])

    def test_create_execution_for_listed_test_keys(self):
        other = make_issue(self.project, self.tester, issue_type=IssueType.TEST, title="Search ok")
        response = self.api.post(f"{self.base()}/test-executions/",
                                 {"name": "CI", "tests": [other.key, self.story.key]}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        detail = self.api.get(f"{self.base()}/test-executions/{response.json()['id']}/").json()
        # Only test issues get runs: the story key is ignored.
        self.assertEqual([r["test_key"] for r in detail["runs"]], [other.key])

    def test_create_execution_rejects_keys_of_another_project(self):
        response = self.api.post(f"{self.base()}/test-executions/",
                                 {"name": "CI", "tests": ["ZZZ-1"]}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_detail_lists_runs_with_automation_and_steps(self):
        execution = services.create_execution(self.project, self.tester, name="E", plan=self.plan)
        detail = self.api.get(f"{self.base()}/test-executions/{execution.pk}/").json()
        run = detail["runs"][0]
        self.assertEqual(run["test_key"], self.test.key)
        self.assertEqual(run["automation"], "auto")
        self.assertEqual(run["status"], "todo")

    def test_runner_claims_and_finishes_execution(self):
        execution = services.create_execution(self.project, self.tester, name="E", plan=self.plan)
        services.request_automated_run(execution, self.tester)
        queued = self.api.get(f"{self.base()}/test-executions/?state=queued").json()
        self.assertEqual([e["id"] for e in queued], [execution.pk])
        self.api.patch(f"{self.base()}/test-executions/{execution.pk}/", {"run_state": "running"}, format="json")
        done = self.api.patch(f"{self.base()}/test-executions/{execution.pk}/", {"run_state": "done"}, format="json")
        self.assertEqual(done.json()["run_state"], "done")
        execution.refresh_from_db()
        self.assertIsNotNone(execution.run_finished_at)

    def test_invalid_run_state_rejected(self):
        execution = services.create_execution(self.project, self.tester, name="E", plan=self.plan)
        response = self.api.patch(f"{self.base()}/test-executions/{execution.pk}/", {"run_state": "boom"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_cannot_queue_twice(self):
        execution = services.create_execution(self.project, self.tester, name="E", plan=self.plan)
        services.request_automated_run(execution, self.tester)
        with self.assertRaises(ValueError):
            services.request_automated_run(execution, self.tester)

    def test_developer_cannot_create_executions(self):
        dev = APIClient()
        dev.force_authenticate(self.dev)
        response = dev.post(f"{self.base()}/test-executions/", {"name": "x"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_skipped_and_na_are_accepted_for_runs(self):
        execution = services.create_execution(self.project, self.tester, name="E", plan=self.plan)
        run = execution.runs.get()
        for status in (RunStatus.SKIPPED, RunStatus.NA):
            response = self.api.patch(f"{self.base()}/test-runs/{run.pk}/",
                                      {"status": status, "comment": "manual"}, format="json")
            self.assertEqual(response.status_code, 200, response.content)
            self.assertEqual(response.json()["status"], status)

    def test_link_creation_from_test_to_story(self):
        response = self.api.post(f"{self.base()}/issues/{self.test.number}/links/",
                                 {"target": self.story.key, "link_type": "tests"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(IssueLink.objects.filter(source=self.test, target=self.story, link_type="tests").exists())

    def test_queue_from_the_web_page(self):
        execution = services.create_execution(self.project, self.tester, name="E", plan=self.plan)
        self.client.force_login(self.tester)
        response = self.client.post(f"/projects/{self.project.key}/tests/executions/{execution.pk}/run/")
        self.assertEqual(response.status_code, 302)
        execution.refresh_from_db()
        self.assertEqual(execution.run_state, RunState.QUEUED)
        self.assertEqual(execution.run_requested_by, self.tester)
