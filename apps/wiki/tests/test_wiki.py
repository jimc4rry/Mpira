from django.test import TestCase

from apps.core.testing import ProjectFixtureMixin, make_issue, make_project
from apps.wiki import services
from apps.wiki.models import Page


class WikiTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.space = self.project.space

    def test_space_created_with_project(self):
        self.assertEqual(self.space.name, self.project.name)

    def test_versioning_and_restore(self):
        page, _ = services.save_page(Page(space=self.space), self.dev, title="Doc", body="v1")
        services.save_page(page, self.pm, title="Doc", body="v2")
        unchanged, changed = services.save_page(page, self.pm, title="Doc", body="v2")
        self.assertFalse(changed)
        self.assertEqual(page.version, 2)
        services.restore_version(page, page.versions.get(version=1), self.pm)
        page.refresh_from_db()
        self.assertEqual(page.version, 3)
        self.assertEqual(page.body, "v1")
        self.assertEqual(list(page.versions.values_list("version", flat=True)), [3, 2, 1])

    def test_issue_references_are_linked(self):
        issue = make_issue(self.project, self.pm)
        page, _ = services.save_page(Page(space=self.space), self.dev, title="Spec", body=f"See [[{issue.key}]]")
        self.assertEqual(list(page.linked_issues.all()), [issue])
        self.assertIn(page, issue.wiki_pages.all())

    def test_embedded_issue_renders_only_for_viewers_with_access(self):
        other = make_project("SEC")
        secret = make_issue(other, self.admin, title="Top secret")
        page, _ = services.save_page(Page(space=self.space), self.dev, title="P", body=f"[[{secret.key}]]")
        self.client.force_login(self.dev)
        response = self.client.get(page.get_absolute_url())
        self.assertNotContains(response, "Top secret")
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(page.get_absolute_url()), "Top secret")

    def test_hierarchy_and_delete_moves_children_up(self):
        parent, _ = services.save_page(Page(space=self.space), self.dev, title="Parent", body="")
        child, _ = services.save_page(Page(space=self.space), self.dev, title="Child", body="", parent=parent)
        self.assertEqual(child.ancestors(), [parent])
        self.client.force_login(self.dev)
        self.client.post(f"/projects/TST/wiki/{parent.pk}/delete/")
        child.refresh_from_db()
        self.assertIsNone(child.parent)

    def test_search(self):
        services.save_page(Page(space=self.space), self.dev, title="Deploy guide", body="railway volumes")
        services.save_page(Page(space=self.space), self.dev, title="Other", body="nothing")
        results = list(services.search_pages([self.space], "railway"))
        self.assertEqual([p.title for p in results], ["Deploy guide"])

    def test_viewer_cannot_edit_and_stale_edit_is_refused(self):
        page, _ = services.save_page(Page(space=self.space), self.dev, title="Doc", body="one")
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(f"/projects/TST/wiki/{page.pk}/edit/").status_code, 403)
        self.client.force_login(self.dev)
        services.save_page(page, self.pm, title="Doc", body="two")
        self.client.post(f"/projects/TST/wiki/{page.pk}/edit/", {"title": "Doc", "body": "mine", "base_version": 1})
        page.refresh_from_db()
        self.assertEqual(page.body, "two")

    def test_markdown_is_sanitized(self):
        page, _ = services.save_page(Page(space=self.space), self.dev, title="XSS", body="<script>alert(1)</script>[x](javascript:alert(1))")
        self.client.force_login(self.dev)
        response = self.client.get(page.get_absolute_url())
        self.assertNotContains(response, "<script>alert(1)</script>", html=False)
        self.assertNotContains(response, 'href="javascript:', html=False)
