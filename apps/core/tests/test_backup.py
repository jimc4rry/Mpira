import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase

from apps.core.testing import ProjectFixtureMixin, make_issue


class BackupTests(ProjectFixtureMixin, TestCase):
    def test_the_dump_holds_the_data_but_no_sessions(self):
        make_issue(self.project, self.pm, title="Kept by the backup")
        with tempfile.TemporaryDirectory() as folder:
            out = StringIO()
            call_command("backup_data", "--dir", folder, stdout=out)
            files = list(Path(folder).glob("mpira-*.json"))
            self.assertEqual(len(files), 1)
            rows = json.loads(files[0].read_text(encoding="utf-8"))
        models = {row["model"] for row in rows}
        self.assertIn("issues.issue", models)
        self.assertIn("accounts.user", models)
        self.assertNotIn("sessions.session", models)
        self.assertIn("Kept by the backup", json.dumps(rows, ensure_ascii=False))
        self.assertIn("Wrote", out.getvalue())
