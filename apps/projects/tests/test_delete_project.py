import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.core.testing import ProjectFixtureMixin, make_issue
from apps.issues.models import Attachment
from apps.projects.models import Project


class DeleteProjectTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.issue = make_issue(self.project, self.dev)
        self.client.force_login(self.admin)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def url(self):
        return f"/projects/{self.project.key}/delete/"

    def test_admin_deletes_with_correct_key(self):
        response = self.client.post(self.url(), {"confirm": self.project.key})
        self.assertRedirects(response, "/projects/")
        self.assertFalse(Project.objects.filter(key="TST").exists())
        self.assertFalse(Issue_exists(self.issue))

    def test_wrong_key_keeps_project(self):
        response = self.client.post(self.url(), {"confirm": "nope"}, follow=True)
        self.assertTrue(Project.objects.filter(key="TST").exists())
        self.assertContains(response, "Type the project key")

    def test_key_match_is_case_insensitive(self):
        self.client.post(self.url(), {"confirm": " tst "})
        self.assertFalse(Project.objects.filter(key="TST").exists())

    def test_project_managers_cannot_delete(self):
        self.client.force_login(self.pm)
        response = self.client.post(self.url(), {"confirm": self.project.key})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Project.objects.filter(key="TST").exists())

    def test_non_members_get_404(self):
        self.client.force_login(self.outsider)
        response = self.client.post(self.url(), {"confirm": self.project.key})
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Project.objects.filter(key="TST").exists())

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url()).status_code, 405)

    def test_attachment_files_are_removed_from_disk(self):
        f = SimpleUploadedFile("a.txt", b"data", content_type="text/plain")
        att = Attachment.objects.create(issue=self.issue, file=f, filename="a.txt", size=4, uploaded_by=self.dev)
        path = att.file.path
        import os

        self.assertTrue(os.path.exists(path))
        self.client.post(self.url(), {"confirm": "TST"})
        self.assertFalse(os.path.exists(path))

    def test_danger_zone_only_for_admins(self):
        response = self.client.get(f"/projects/{self.project.key}/settings/")
        self.assertContains(response, "Delete project permanently")
        self.client.force_login(self.pm)
        response = self.client.get(f"/projects/{self.project.key}/settings/")
        self.assertNotContains(response, "Delete project permanently")


def Issue_exists(issue):
    from apps.issues.models import Issue

    return Issue.objects.filter(pk=issue.pk).exists()
