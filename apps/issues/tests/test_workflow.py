from django.test import TestCase

from apps.agile import board as board_service
from apps.agile.models import BoardColumn
from apps.core.testing import ProjectFixtureMixin, make_issue
from apps.issues import services, workflow
from apps.issues.models import Activity, Issue, Status, WorkflowStatus


class WorkflowDefaultsTests(ProjectFixtureMixin, TestCase):
    def test_new_project_gets_default_statuses_and_transitions(self):
        keys = [s.key for s in workflow.statuses(self.project)]
        self.assertEqual(keys, ["todo", "in_progress", "in_review", "done", "canceled"])
        self.assertEqual(workflow.initial_key(self.project), "todo")
        self.assertEqual(workflow.done_keys(self.project), {"done", "canceled"})
        self.assertEqual(sorted(workflow.transition_map(self.project)["todo"]), ["canceled", "in_progress"])

    def test_existing_issues_keep_working_with_default_keys(self):
        issue = make_issue(self.project, self.dev)
        services.transition_issue(issue, self.dev, "in_progress")
        issue.refresh_from_db()
        self.assertEqual(issue.status, "in_progress")
        self.assertEqual(issue.get_status_display(), "In Progress")


class WorkflowEditingTests(ProjectFixtureMixin, TestCase):
    def test_add_status_is_reachable_both_ways_by_default(self):
        qa = workflow.add_status(self.project, "QA")
        self.assertEqual(qa.key, "qa")
        transitions = workflow.transition_map(self.project)
        self.assertIn("qa", transitions["todo"])
        self.assertIn("qa", transitions["done"])
        self.assertIn("todo", transitions["qa"])
        self.assertNotIn("qa", transitions["qa"])

    def test_add_status_with_same_name_rejected_and_keys_stay_unique(self):
        with self.assertRaises(workflow.WorkflowError):
            workflow.add_status(self.project, "to do")
        a = workflow.add_status(self.project, "Blocked!")
        b = workflow.add_status(self.project, "Blocked?")
        self.assertEqual(a.key, "blocked")
        self.assertEqual(b.key, "blocked-2")

    def test_greek_only_names_get_a_usable_key(self):
        status = workflow.add_status(self.project, "Σε αναμονή")
        self.assertTrue(status.key)
        self.assertTrue(status.key.isascii())

    def test_custom_status_is_usable_in_transitions(self):
        qa = workflow.add_status(self.project, "QA")
        issue = make_issue(self.project, self.dev)
        services.transition_issue(issue, self.dev, "qa")
        issue.refresh_from_db()
        self.assertEqual(issue.status, "qa")
        self.assertEqual(issue.get_status_display(), "QA")
        self.assertIsNone(issue.resolved_at)

    def test_done_status_sets_resolved_at(self):
        final = workflow.add_status(self.project, "Released", counts_as_done=True)
        issue = make_issue(self.project, self.dev)
        services.transition_issue(issue, self.dev, "in_progress")
        services.transition_issue(issue, self.dev, final.key)
        issue.refresh_from_db()
        self.assertTrue(issue.is_done)
        self.assertIsNotNone(issue.resolved_at)

    def test_rename_and_change_done_flag(self):
        qa = workflow.add_status(self.project, "QA")
        workflow.update_status(qa, name="Testing", counts_as_done=True)
        qa.refresh_from_db()
        self.assertEqual(qa.name, "Testing")
        self.assertIn("qa", workflow.done_keys(self.project))

    def test_last_done_status_cannot_be_unmarked(self):
        canceled = WorkflowStatus.objects.get(project=self.project, key="canceled")
        workflow.update_status(canceled, counts_as_done=False)  # done still counts, so this is allowed
        done = WorkflowStatus.objects.get(project=self.project, key="done")
        with self.assertRaises(workflow.WorkflowError):
            workflow.update_status(done, counts_as_done=False)

    def test_initial_status_can_be_moved(self):
        review = WorkflowStatus.objects.get(project=self.project, key="in_review")
        workflow.update_status(review, is_initial=True)
        self.assertEqual(workflow.initial_key(self.project), "in_review")
        self.assertEqual(WorkflowStatus.objects.filter(project=self.project, is_initial=True).count(), 1)

    def test_new_issues_start_in_initial_status(self):
        review = WorkflowStatus.objects.get(project=self.project, key="in_review")
        workflow.update_status(review, is_initial=True)
        issue = make_issue(self.project, self.dev)
        self.assertEqual(issue.status, "in_review")

    def test_delete_status_moves_issues_and_logs_it(self):
        qa = workflow.add_status(self.project, "QA")
        issue = make_issue(self.project, self.dev)
        services.transition_issue(issue, self.dev, "qa")
        target = WorkflowStatus.objects.get(project=self.project, key="in_progress")
        workflow.delete_status(qa, target)
        issue.refresh_from_db()
        self.assertEqual(issue.status, "in_progress")
        self.assertTrue(Activity.objects.filter(issue=issue, field="status", old_value="qa", new_value="in_progress").exists())
        self.assertFalse(WorkflowStatus.objects.filter(project=self.project, key="qa").exists())

    def test_delete_requires_target_when_issues_exist(self):
        qa = workflow.add_status(self.project, "QA")
        issue = make_issue(self.project, self.dev)
        services.transition_issue(issue, self.dev, "qa")
        with self.assertRaises(workflow.WorkflowError):
            workflow.delete_status(qa)

    def test_initial_and_last_done_cannot_be_deleted(self):
        todo = WorkflowStatus.objects.get(project=self.project, key="todo")
        with self.assertRaises(workflow.WorkflowError):
            workflow.delete_status(todo, WorkflowStatus.objects.get(project=self.project, key="done"))
        workflow.delete_status(WorkflowStatus.objects.get(project=self.project, key="canceled"))
        done = WorkflowStatus.objects.get(project=self.project, key="done")
        with self.assertRaises(workflow.WorkflowError):
            workflow.delete_status(done, WorkflowStatus.objects.get(project=self.project, key="todo"))

    def test_transition_matrix_must_leave_every_status_an_exit(self):
        allowed = {k: set() for k in workflow.status_map(self.project)}
        allowed["todo"] = {"in_progress"}
        allowed["in_progress"] = {"todo"}
        allowed["in_review"] = {"done"}
        allowed["done"] = set()  # a dead end
        allowed["canceled"] = {"todo"}
        with self.assertRaises(workflow.WorkflowError):
            workflow.save_transitions(self.project, allowed)

    def test_saved_matrix_restricts_moves(self):
        allowed = {k: set() for k in workflow.status_map(self.project)}
        allowed["todo"] = {"done"}  # shortcut only from To Do
        allowed["in_progress"] = {"todo"}
        allowed["in_review"] = {"in_progress"}
        allowed["done"] = {"todo"}
        allowed["canceled"] = {"todo"}
        workflow.save_transitions(self.project, allowed)
        issue = make_issue(self.project, self.dev)
        services.transition_issue(issue, self.dev, "done")
        issue.refresh_from_db()
        self.assertEqual(issue.status, "done")
        with self.assertRaises(workflow.WorkflowError):
            services.transition_issue(issue, self.dev, "in_progress")

    def test_unknown_status_rejected(self):
        issue = make_issue(self.project, self.dev)
        with self.assertRaises(workflow.WorkflowError):
            services.transition_issue(issue, self.dev, "nonexistent")


class WorkflowBoardIntegrationTests(ProjectFixtureMixin, TestCase):
    def test_added_status_lands_in_last_column_and_is_on_board(self):
        board_service.ensure_columns(self.project)
        qa = workflow.add_status(self.project, "QA")
        columns = board_service.ensure_columns(self.project)
        self.assertIn(qa.key, columns[-1].statuses)
        self.assertEqual(sum(c.statuses.count(qa.key) for c in columns), 1)

    def test_place_status_moves_it_to_chosen_column(self):
        columns = board_service.ensure_columns(self.project)
        qa = workflow.add_status(self.project, "QA")
        board_service.place_status(self.project, qa.key, columns[1].pk)
        self.assertIn("qa", BoardColumn.objects.get(pk=columns[1].pk).statuses)
        self.assertNotIn("qa", BoardColumn.objects.get(pk=columns[-1].pk).statuses)

    def test_deleted_status_is_removed_from_columns(self):
        columns = board_service.ensure_columns(self.project)
        qa = workflow.add_status(self.project, "QA")
        board_service.ensure_columns(self.project)
        workflow.delete_status(qa, WorkflowStatus.objects.get(project=self.project, key="done"))
        board_service.ensure_columns(self.project)
        for col in BoardColumn.objects.filter(project=self.project):
            self.assertNotIn("qa", col.statuses)

    def test_custom_done_status_hides_from_open_lists_and_counts(self):
        final = workflow.add_status(self.project, "Released", counts_as_done=True)
        issue = make_issue(self.project, self.dev)
        services.transition_issue(issue, self.dev, "in_progress")
        services.transition_issue(issue, self.dev, final.key)
        self.client.force_login(self.dev)
        response = self.client.get(f"/projects/{self.project.key}/issues/?status=open")
        self.assertNotContains(response, issue.title)
        response = self.client.get(f"/projects/{self.project.key}/issues/?status=released")
        self.assertContains(response, issue.title)

    def test_api_move_uses_project_statuses(self):
        self.client.force_login(self.dev)
        qa = workflow.add_status(self.project, "QA")
        issue = make_issue(self.project, self.dev)
        response = self.client.post(
            f"/api/v1/projects/{self.project.key}/issues/{issue.number}/move/",
            {"status": qa.key},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "qa")


class WorkflowPageTests(ProjectFixtureMixin, TestCase):
    url = "/projects/TST/workflow/"

    def test_only_managers_reach_the_page(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.pm)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_add_edit_delete_and_transitions_through_the_page(self):
        self.client.force_login(self.pm)
        self.client.post(self.url, {"action": "add", "name": "QA", "column": ""})
        qa = WorkflowStatus.objects.get(project=self.project, key="qa")
        self.assertTrue(any("qa" in c.statuses for c in BoardColumn.objects.filter(project=self.project)))

        self.client.post(self.url, {"action": "update", "status": "qa", "name": "Testing", "counts_as_done": "on"})
        qa.refresh_from_db()
        self.assertEqual(qa.name, "Testing")
        self.assertTrue(qa.counts_as_done)

        data = {"action": "transitions"}
        for source in workflow.status_map(self.project):
            for target in workflow.status_map(self.project):
                if source != target:
                    data[f"next|{source}|{target}"] = "on"
        data.pop("next|todo|qa")
        self.client.post(self.url, data)
        workflow.forget(self.project)  # the test's instance cached the old matrix
        self.assertNotIn("qa", workflow.transition_map(self.project)["todo"])

        self.client.post(self.url, {"action": "delete", "status": "qa", "move_to": WorkflowStatus.objects.get(project=self.project, key="done").pk})
        self.assertFalse(WorkflowStatus.objects.filter(project=self.project, key="qa").exists())
