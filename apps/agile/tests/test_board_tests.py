from django.test import TestCase

from apps.agile import services
from apps.agile.models import Sprint
from apps.core.testing import ProjectFixtureMixin, make_issue
from apps.issues.models import IssueType


class TestCardsOnBoardTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.sprint = Sprint.objects.create(project=self.project, name="S1")
        self.test_issue = make_issue(self.project, self.tester, issue_type=IssueType.TEST, title="Login test", sprint=self.sprint)
        services.start_sprint(self.sprint)

    def test_test_cards_appear_in_sprint_board(self):
        self.client.force_login(self.viewer)
        response = self.client.get(f"/projects/{self.project.key}/board/")
        self.assertContains(response, "Login test")
        self.assertContains(response, 'data-type="test"')

    def test_test_cards_appear_in_backlog(self):
        self.client.force_login(self.viewer)
        response = self.client.get(f"/projects/{self.project.key}/backlog/")
        self.assertContains(response, "Login test")

    def test_epics_stay_off_the_board(self):
        make_issue(self.project, self.pm, issue_type=IssueType.EPIC, title="Big epic", sprint=self.sprint)
        self.client.force_login(self.viewer)
        response = self.client.get(f"/projects/{self.project.key}/board/")
        self.assertNotContains(response, "Big epic")
