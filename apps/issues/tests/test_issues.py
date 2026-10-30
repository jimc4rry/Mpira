import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.core.models import Notification
from apps.core.testing import ProjectFixtureMixin, make_issue
from apps.issues import services
from apps.issues.models import Activity, CustomFieldDefinition, Issue, IssueLink, IssueType, Status


class IssueCrudTests(ProjectFixtureMixin, TestCase):
    def test_create_issue_via_form_assigns_sequential_keys(self):
        self.client.force_login(self.dev)
        for title in ("First", "Second"):
            response = self.client.post(
                "/projects/TST/issues/new/",
                {"issue_type": "story", "title": title, "priority": "medium", "story_points": 3},
            )
            self.assertEqual(response.status_code, 302)
        keys = [i.key for i in Issue.objects.order_by("number")]
        self.assertEqual(keys, ["TST-1", "TST-2"])
        issue = Issue.objects.get(number=1)
        self.assertEqual(issue.reporter, self.dev)
        self.assertIn(self.dev, issue.watchers.all())
        self.assertTrue(issue.activity.filter(kind=Activity.Kind.CREATED).exists())

    def test_subtask_requires_parent(self):
        self.client.force_login(self.dev)
        response = self.client.post("/projects/TST/issues/new/", {"issue_type": "subtask", "title": "x", "priority": "medium"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Issue.objects.exists())

    def test_viewer_cannot_create(self):
        self.client.force_login(self.viewer)
        response = self.client.post("/projects/TST/issues/new/", {"issue_type": "task", "title": "x", "priority": "medium"})
        self.assertEqual(response.status_code, 403)

    def test_edit_records_field_activity_and_notifies_new_assignee(self):
        issue = make_issue(self.project, self.pm, title="Old")
        self.client.force_login(self.pm)
        response = self.client.post(
            f"/projects/TST/issues/{issue.number}/edit/",
            {"issue_type": "story", "title": "New", "priority": "high", "assignee": self.dev.pk},
        )
        self.assertEqual(response.status_code, 302)
        changes = {a.field: (a.old_value, a.new_value) for a in issue.activity.filter(kind=Activity.Kind.FIELD)}
        self.assertEqual(changes["title"], ("Old", "New"))
        self.assertEqual(changes["priority"], ("medium", "high"))
        self.assertTrue(Notification.objects.filter(recipient=self.dev, kind=Notification.Kind.ASSIGNED).exists())

    def test_delete_requires_pm(self):
        issue = make_issue(self.project, self.dev)
        self.client.force_login(self.dev)
        self.assertEqual(self.client.post(f"/projects/TST/issues/{issue.number}/delete/").status_code, 403)
        self.client.force_login(self.pm)
        self.client.post(f"/projects/TST/issues/{issue.number}/delete/")
        self.assertFalse(Issue.objects.filter(pk=issue.pk).exists())

    def test_detail_page_renders(self):
        issue = make_issue(self.project, self.pm, description="Hello **world** [[TST-1]] @dev")
        self.client.force_login(self.viewer)
        response = self.client.get(issue.get_absolute_url())
        self.assertContains(response, "<strong>world</strong>", html=False)
        self.assertContains(response, "issue-chip")
        self.assertContains(response, 'class="mention"')


class WorkflowTests(ProjectFixtureMixin, TestCase):
    def test_valid_path_to_done_sets_resolved_at(self):
        issue = make_issue(self.project, self.dev)
        for status in (Status.IN_PROGRESS, Status.IN_REVIEW, Status.DONE):
            services.transition_issue(issue, self.dev, status)
        issue.refresh_from_db()
        self.assertEqual(issue.status, Status.DONE)
        self.assertIsNotNone(issue.resolved_at)
        self.assertEqual(issue.activity.filter(kind=Activity.Kind.TRANSITION).count(), 3)

    def test_skipping_states_is_rejected(self):
        issue = make_issue(self.project, self.dev)
        with self.assertRaises(services.WorkflowError):
            services.transition_issue(issue, self.dev, Status.DONE)
        issue.refresh_from_db()
        self.assertEqual(issue.status, Status.TODO)

    def test_reopen_clears_resolved_at(self):
        issue = make_issue(self.project, self.dev)
        for status in (Status.IN_PROGRESS, Status.IN_REVIEW, Status.DONE, Status.TODO):
            services.transition_issue(issue, self.dev, status)
        issue.refresh_from_db()
        self.assertIsNone(issue.resolved_at)

    def test_transition_view_shows_error(self):
        issue = make_issue(self.project, self.dev)
        self.client.force_login(self.dev)
        self.client.post(f"/projects/TST/issues/{issue.number}/transition/", {"status": "done"})
        issue.refresh_from_db()
        self.assertEqual(issue.status, Status.TODO)


class CommentsMentionsTests(ProjectFixtureMixin, TestCase):
    def test_mention_notifies_member_and_adds_watcher(self):
        issue = make_issue(self.project, self.pm)
        services.add_comment(issue, self.pm, "Hey @dev and @outsider, have a look")
        self.assertTrue(Notification.objects.filter(recipient=self.dev, kind=Notification.Kind.MENTION).exists())
        # Not a member of the project → never notified, never leaks the issue.
        self.assertFalse(Notification.objects.filter(recipient=self.outsider).exists())
        self.assertIn(self.dev, issue.watchers.all())

    def test_watchers_are_notified_of_comments(self):
        issue = make_issue(self.project, self.pm)
        issue.watchers.add(self.tester)
        services.add_comment(issue, self.dev, "Progress update")
        self.assertTrue(Notification.objects.filter(recipient=self.tester, kind=Notification.Kind.COMMENT).exists())
        self.assertFalse(Notification.objects.filter(recipient=self.dev).exists())

    def test_viewer_cannot_comment(self):
        issue = make_issue(self.project, self.pm)
        self.client.force_login(self.viewer)
        response = self.client.post(f"/projects/TST/issues/{issue.number}/comments/", {"body": "hi"})
        self.assertEqual(response.status_code, 403)

    def test_email_addresses_are_not_mentions(self):
        issue = make_issue(self.project, self.pm)
        services.add_comment(issue, self.pm, "mail dev@example.com")
        self.assertFalse(Notification.objects.filter(recipient=self.dev, kind=Notification.Kind.MENTION).exists())


class CustomFieldTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        CustomFieldDefinition.objects.create(
            project=self.project, name="Impact", key="impact", field_type="select", options="Low,High",
            issue_type=IssueType.BUG, required=True,
        )

    def test_required_select_validated_for_bugs_only(self):
        self.client.force_login(self.dev)
        r = self.client.post("/projects/TST/issues/new/", {"issue_type": "bug", "title": "b", "priority": "medium"})
        self.assertEqual(r.status_code, 200)
        r = self.client.post("/projects/TST/issues/new/", {"issue_type": "bug", "title": "b", "priority": "medium", "cf_impact": "High"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Issue.objects.get().custom_fields, {"impact": "High"})
        r = self.client.post("/projects/TST/issues/new/", {"issue_type": "task", "title": "t", "priority": "medium"})
        self.assertEqual(r.status_code, 302)


class LinkTests(ProjectFixtureMixin, TestCase):
    def test_only_tests_can_use_tests_link(self):
        story = make_issue(self.project, self.pm)
        task = make_issue(self.project, self.pm, issue_type=IssueType.TASK)
        with self.assertRaises(services.WorkflowError):
            services.link_issues(task, story, IssueLink.LinkType.TESTS, self.pm)
        test = make_issue(self.project, self.pm, issue_type=IssueType.TEST)
        services.link_issues(test, story, IssueLink.LinkType.TESTS, self.pm)
        self.assertEqual(story.inward_links.count(), 1)


class AttachmentTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_upload_and_permission_checked_download(self):
        issue = make_issue(self.project, self.pm)
        self.client.force_login(self.dev)
        f = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")
        self.client.post(f"/projects/TST/issues/{issue.number}/attachments/", {"file": f})
        att = issue.attachments.get()
        url = f"/projects/TST/issues/{issue.number}/attachments/{att.pk}/"
        self.assertEqual(b"".join(self.client.get(url).streaming_content), b"hello")
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)

    @override_settings(MAX_ATTACHMENT_SIZE=3)
    def test_size_limit(self):
        issue = make_issue(self.project, self.pm)
        self.client.force_login(self.dev)
        f = SimpleUploadedFile("big.txt", b"too big", content_type="text/plain")
        self.client.post(f"/projects/TST/issues/{issue.number}/attachments/", {"file": f})
        self.assertFalse(issue.attachments.exists())
