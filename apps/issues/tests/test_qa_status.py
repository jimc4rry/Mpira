from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from apps.agile import board
from apps.core.testing import make_project
from apps.issues import workflow


class AddQaStatusTests(TestCase):
    def setUp(self):
        self.project = make_project("QAS")

    def run_command(self, *args):
        out = StringIO()
        call_command("add_qa_status", *args, stdout=out)
        return out.getvalue()

    def qa_statuses(self):
        return [s for s in workflow.statuses(self.project) if s.name.lower() == "qa"]

    def columns(self):
        return board.ensure_columns(self.project)

    def test_the_project_gets_a_qa_status_and_a_column_before_done(self):
        self.run_command()
        self.assertEqual(len(self.qa_statuses()), 1)
        names = [c.name for c in self.columns()]
        self.assertIn("QA", names)
        done = workflow.done_keys(self.project)
        done_position = next(i for i, c in enumerate(self.columns()) if set(c.statuses) & done)
        self.assertLess(names.index("QA"), done_position)
        self.assertIn(self.qa_statuses()[0].key, self.columns()[names.index("QA")].statuses)

    def test_running_it_again_changes_nothing(self):
        self.run_command()
        out = self.run_command()
        self.assertEqual(len(self.qa_statuses()), 1)
        self.assertEqual([c.name for c in self.columns()].count("QA"), 1)
        self.assertIn("nothing to do", out)

    def test_a_dry_run_writes_nothing(self):
        before = [c.name for c in self.columns()]
        out = self.run_command("--dry-run")
        self.assertEqual(self.qa_statuses(), [])
        self.assertEqual([c.name for c in self.columns()], before)
        self.assertIn("status QA added", out)
