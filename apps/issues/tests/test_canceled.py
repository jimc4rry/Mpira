from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.agile import board
from apps.core.testing import ProjectFixtureMixin, make_issue, make_project
from apps.issues import services, workflow
from apps.issues.models import WorkflowStatus


class CanceledStatusTests(ProjectFixtureMixin, TestCase):
    def run_command(self, *args):
        out = StringIO()
        call_command("add_canceled_status", *args, stdout=out)
        return out.getvalue()

    def canceled(self, project):
        workflow.forget(project)  # the command works on its own copies of the project: read fresh data
        return [s for s in workflow.statuses(project) if s.key == workflow.CANCELED_KEY]

    def test_a_new_project_has_canceled_and_it_counts_as_done(self):
        project = make_project("CNL")
        found = self.canceled(project)
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0].counts_as_done)
        self.assertIn(workflow.CANCELED_KEY, workflow.done_keys(project))

    def test_an_older_project_gets_canceled_on_the_board_and_running_again_changes_nothing(self):
        project = make_project("OLD")
        WorkflowStatus.objects.filter(project=project, key=workflow.CANCELED_KEY).delete()
        workflow.forget(project)
        self.assertEqual(self.canceled(project), [])
        self.run_command()
        self.assertEqual(len(self.canceled(project)), 1)
        self.assertTrue(any(workflow.CANCELED_KEY in c.statuses for c in board.ensure_columns(project)))
        out = self.run_command()
        self.assertEqual(len(self.canceled(project)), 1)
        self.assertEqual(sum(c.statuses.count(workflow.CANCELED_KEY) for c in board.ensure_columns(project)), 1)
        self.assertIn("nothing to do", out)

    def test_a_dry_run_writes_nothing(self):
        project = make_project("DRY")
        WorkflowStatus.objects.filter(project=project, key=workflow.CANCELED_KEY).delete()
        workflow.forget(project)
        before = [c.name for c in board.ensure_columns(project)]
        out = self.run_command("--dry-run")
        self.assertEqual(self.canceled(project), [])
        self.assertEqual([c.name for c in board.ensure_columns(project)], before)
        self.assertIn("status Canceled added", out)

    def test_a_ticket_can_be_moved_to_canceled_from_its_current_status(self):
        issue = make_issue(self.project, self.pm, title="Duplicate of another ticket")
        services.transition_issue(issue, self.pm, workflow.CANCELED_KEY)
        issue.refresh_from_db()
        self.assertEqual(issue.status, workflow.CANCELED_KEY)
        self.assertIsNotNone(issue.resolved_at)
