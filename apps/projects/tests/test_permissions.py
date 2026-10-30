from django.test import TestCase

from apps.core.testing import ProjectFixtureMixin
from apps.projects.permissions import can, role_for, visible_projects


class PermissionMatrixTests(ProjectFixtureMixin, TestCase):
    def test_roles(self):
        self.assertEqual(role_for(self.admin, self.project), "admin")
        self.assertEqual(role_for(self.pm, self.project), "pm")
        self.assertIsNone(role_for(self.outsider, self.project))

    def test_capabilities(self):
        p = self.project
        self.assertTrue(can(self.viewer, p, "view"))
        self.assertFalse(can(self.viewer, p, "edit_issues"))
        self.assertFalse(can(self.viewer, p, "comment"))
        self.assertTrue(can(self.dev, p, "edit_issues"))
        self.assertFalse(can(self.dev, p, "manage_sprints"))
        self.assertTrue(can(self.pm, p, "manage_sprints"))
        self.assertTrue(can(self.tester, p, "manage_tests"))
        self.assertFalse(can(self.dev, p, "manage_tests"))
        self.assertTrue(can(self.admin, p, "manage_project"))
        self.assertFalse(can(self.outsider, p, "view"))

    def test_visible_projects(self):
        self.assertIn(self.project, visible_projects(self.dev))
        self.assertIn(self.project, visible_projects(self.admin))
        self.assertNotIn(self.project, visible_projects(self.outsider))

    def test_non_member_gets_404_member_without_capability_gets_403(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get("/projects/TST/").status_code, 404)
        self.assertEqual(self.client.get("/projects/TST/issues/").status_code, 404)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get("/projects/TST/").status_code, 200)
        self.assertEqual(self.client.get("/projects/TST/issues/new/").status_code, 403)
        self.assertEqual(self.client.get("/projects/TST/settings/").status_code, 403)

    def test_pm_manages_members(self):
        self.client.force_login(self.pm)
        response = self.client.post("/projects/TST/settings/members/add/", {"user": self.outsider.pk, "role": "developer"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(can(type(self.outsider).objects.get(pk=self.outsider.pk), self.project, "edit_issues"))

    def test_project_creation_creates_wiki_space_and_membership(self):
        self.client.force_login(self.pm)
        response = self.client.post("/projects/new/", {"name": "Second", "key": "sec", "description": "", "lead": self.pm.pk})
        self.assertRedirects(response, "/projects/SEC/")
        from apps.projects.models import Project

        project = Project.objects.get(key="SEC")
        self.assertTrue(hasattr(project, "space"))
        self.assertEqual(role_for(self.pm, project), "pm")

    def test_developer_cannot_create_projects(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get("/projects/new/").status_code, 403)
