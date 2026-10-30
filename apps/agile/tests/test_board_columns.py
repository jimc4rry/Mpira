from django.test import TestCase

from apps.agile import board as board_service
from apps.agile.models import BoardColumn
from apps.core.testing import ProjectFixtureMixin, make_issue
from apps.issues import workflow


class BoardColumnRulesTests(ProjectFixtureMixin, TestCase):
    def test_defaults_are_created_once(self):
        cols = board_service.ensure_columns(self.project)
        self.assertEqual([c.statuses for c in cols], [["todo"], ["in_progress"], ["in_review"], ["done", "canceled"]])
        self.assertEqual(len(board_service.ensure_columns(self.project)), 4)

    def test_add_rename_and_reorder(self):
        board_service.ensure_columns(self.project)
        added = board_service.add_column(self.project, "Blocked")
        self.assertEqual(added.position, 4)
        board_service.rename_column(added, "Waiting")
        board_service.move_column(added, "up")
        names = [c.name for c in BoardColumn.objects.filter(project=self.project)]
        self.assertEqual(names[3:], ["Waiting", "Done"])
        positions = list(BoardColumn.objects.filter(project=self.project).values_list("position", flat=True))
        self.assertEqual(positions, [0, 1, 2, 3, 4])

    def test_move_edges_are_noops(self):
        cols = board_service.ensure_columns(self.project)
        board_service.move_column(cols[0], "up")
        board_service.move_column(cols[-1], "down")
        self.assertEqual(BoardColumn.objects.get(pk=cols[0].pk).position, 0)

    def test_duplicate_and_empty_names_rejected(self):
        board_service.ensure_columns(self.project)
        with self.assertRaises(board_service.BoardError):
            board_service.add_column(self.project, "to do")
        with self.assertRaises(board_service.BoardError):
            board_service.add_column(self.project, "   ")

    def test_delete_moves_statuses_and_requires_target(self):
        cols = board_service.ensure_columns(self.project)
        with self.assertRaises(board_service.BoardError):
            board_service.delete_column(cols[0])
        board_service.delete_column(cols[0], cols[1])
        remaining = list(BoardColumn.objects.filter(project=self.project))
        self.assertEqual(len(remaining), 3)
        self.assertEqual(remaining[0].statuses, ["in_progress", "todo"])
        self.assertEqual([c.position for c in remaining], [0, 1, 2])

    def test_delete_empty_column_needs_no_target(self):
        board_service.ensure_columns(self.project)
        empty = board_service.add_column(self.project, "Spare")
        board_service.delete_column(empty)
        self.assertFalse(BoardColumn.objects.filter(name="Spare").exists())

    def test_last_column_cannot_be_deleted(self):
        cols = board_service.ensure_columns(self.project)
        for c in cols[1:]:
            board_service.delete_column(c, cols[0])
        with self.assertRaises(board_service.BoardError):
            board_service.delete_column(cols[0])

    def test_assignment_must_cover_every_status_once(self):
        cols = board_service.ensure_columns(self.project)
        partial = {"todo": cols[0].pk}
        with self.assertRaises(board_service.BoardError):
            board_service.set_status_assignment(self.project, partial)
        keys = list(workflow.status_map(self.project))
        full = {s: cols[0].pk for s in keys}
        board_service.set_status_assignment(self.project, full)
        self.assertEqual(sorted(BoardColumn.objects.get(pk=cols[0].pk).statuses), sorted(keys))
        self.assertEqual(BoardColumn.objects.get(pk=cols[1].pk).statuses, [])


class BoardViewTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.cols = board_service.ensure_columns(self.project)
        self.issue = make_issue(self.project, self.dev, title="Card")

    def test_board_renders_columns_in_order_and_cards_in_their_column(self):
        self.client.force_login(self.viewer)
        html = self.client.get(f"/projects/{self.project.key}/board/?scope=all").content.decode()
        self.assertLess(html.index("To Do"), html.index("Done"))
        self.assertIn('data-status="todo"', html)

    def test_reordered_column_and_grouped_statuses(self):
        review = self.cols[2]
        board_service.move_column(review, "up")
        board_service.move_column(review, "up")  # now first
        board_service.set_status_assignment(
            self.project,
            {
                "todo": self.cols[0].pk,
                "in_progress": self.cols[1].pk,
                "in_review": self.cols[1].pk,
                "done": self.cols[3].pk,
                "canceled": self.cols[3].pk,
            },
        )
        self.client.force_login(self.viewer)
        response = self.client.get(f"/projects/{self.project.key}/board/?scope=all")
        labels = [c["label"] for c in response.context["columns"]]
        self.assertEqual(labels[0], "In Review")
        grouped = next(c for c in response.context["columns"] if c["label"] == "In Progress")
        self.assertEqual(grouped["statuses"], ["in_progress", "in_review"])

    def test_empty_column_has_no_drop_target(self):
        spare = board_service.add_column(self.project, "Spare")
        self.client.force_login(self.viewer)
        response = self.client.get(f"/projects/{self.project.key}/board/?scope=all")
        spare_col = next(c for c in response.context["columns"] if c["pk"] == spare.pk)
        self.assertEqual(spare_col["status"], "")

    def test_only_managers_see_configuration_link(self):
        self.client.force_login(self.dev)
        self.assertNotContains(self.client.get(f"/projects/{self.project.key}/board/?scope=all"), "/board/settings/")
        self.client.force_login(self.pm)
        self.assertContains(self.client.get(f"/projects/{self.project.key}/board/?scope=all"), "/board/settings/")

    def test_settings_forms_end_to_end(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(f"/projects/{self.project.key}/board/settings/").status_code, 403)

        self.client.force_login(self.pm)
        url = f"/projects/{self.project.key}/board/settings/"
        self.client.post(url, {"action": "add", "name": "QA"})
        qa = BoardColumn.objects.get(project=self.project, name="QA")
        self.client.post(url, {"action": "move", "column": qa.pk, "direction": "up"})
        self.assertEqual(BoardColumn.objects.get(pk=qa.pk).position, 3)
        self.client.post(url, {"action": "rename", "column": qa.pk, "name": "Testing"})
        self.assertTrue(BoardColumn.objects.filter(pk=qa.pk, name="Testing").exists())

        assign = {f"status_{s}": str(self.cols[0].pk) for s in workflow.status_map(self.project)}
        assign["status_done"] = str(qa.pk)
        self.client.post(url, {"action": "assign", **assign})
        self.assertEqual(BoardColumn.objects.get(pk=qa.pk).statuses, ["done"])

        response = self.client.post(url, {"action": "delete", "column": qa.pk, "move_to": self.cols[0].pk})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(BoardColumn.objects.filter(pk=qa.pk).exists())
        self.assertIn("done", BoardColumn.objects.get(pk=self.cols[0].pk).statuses)

    def test_workflow_still_enforced_for_moves(self):
        # Moving a To Do card straight to a column whose status is Done is refused.
        self.client.force_login(self.dev)
        response = self.client.post(
            f"/api/v1/projects/{self.project.key}/issues/{self.issue.number}/move/",
            {"status": "done"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
