import datetime

from django.test import TestCase
from django.utils import timezone

from apps.agile import services
from apps.agile.models import Sprint
from apps.core.testing import ProjectFixtureMixin, make_issue
from apps.issues import services as issue_services
from apps.issues.models import Activity, Status


def finish(issue, user):
    for status in (Status.IN_PROGRESS, Status.IN_REVIEW, Status.DONE):
        issue_services.transition_issue(issue, user, status)


class SprintLifecycleTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.sprint = Sprint.objects.create(project=self.project, name="S1")
        self.a = make_issue(self.project, self.pm, story_points=5, sprint=self.sprint)
        self.b = make_issue(self.project, self.pm, story_points=3, sprint=self.sprint)

    def test_full_lifecycle(self):
        today = timezone.localdate()
        services.start_sprint(self.sprint, today, today + datetime.timedelta(days=9))
        self.assertEqual(self.sprint.state, Sprint.State.ACTIVE)
        self.assertEqual(self.sprint.committed_points, 8)

        finish(self.a, self.dev)
        nxt = Sprint.objects.create(project=self.project, name="S2")
        moved = services.complete_sprint(self.sprint, move_to=nxt)

        self.sprint.refresh_from_db()
        self.b.refresh_from_db()
        self.a.refresh_from_db()
        self.assertEqual(moved, 1)
        self.assertEqual(self.sprint.state, Sprint.State.CLOSED)
        self.assertEqual(self.sprint.completed_points, 5)
        self.assertEqual(self.a.sprint, self.sprint)  # done issues stay
        self.assertEqual(self.b.sprint, nxt)  # incomplete issues move on
        self.assertEqual(set(self.sprint.final_scope), {str(self.a.pk), str(self.b.pk)})

        vel = services.velocity(self.project)
        self.assertEqual(vel["average"], 5)

    def test_complete_to_backlog(self):
        services.start_sprint(self.sprint)
        services.complete_sprint(self.sprint)
        self.a.refresh_from_db()
        self.assertIsNone(self.a.sprint)

    def test_only_one_active_sprint(self):
        services.start_sprint(self.sprint)
        other = Sprint.objects.create(project=self.project, name="S2")
        make_issue(self.project, self.pm, sprint=other)
        with self.assertRaises(services.SprintError):
            services.start_sprint(other)

    def test_cannot_start_empty_sprint(self):
        empty = Sprint.objects.create(project=self.project, name="Empty")
        with self.assertRaises(services.SprintError):
            services.start_sprint(empty)

    def test_cannot_complete_future_sprint(self):
        with self.assertRaises(services.SprintError):
            services.complete_sprint(self.sprint)

    def test_end_before_start_rejected(self):
        today = timezone.localdate()
        with self.assertRaises(services.SprintError):
            services.start_sprint(self.sprint, today, today - datetime.timedelta(days=1))

    def test_html_flow_requires_pm(self):
        self.client.force_login(self.dev)
        today = timezone.localdate()
        data = {"start_date": today.isoformat(), "end_date": (today + datetime.timedelta(days=7)).isoformat()}
        self.assertEqual(self.client.post(f"/projects/TST/sprints/{self.sprint.pk}/start/", data).status_code, 403)
        self.client.force_login(self.pm)
        self.client.post(f"/projects/TST/sprints/{self.sprint.pk}/start/", data)
        self.sprint.refresh_from_db()
        self.assertTrue(self.sprint.is_active)
        self.client.post(f"/projects/TST/sprints/{self.sprint.pk}/complete/", {"move_to": ""})
        self.sprint.refresh_from_db()
        self.assertEqual(self.sprint.state, Sprint.State.CLOSED)

    def test_board_backlog_reports_render(self):
        services.start_sprint(self.sprint)
        self.client.force_login(self.viewer)
        for url in ("/projects/TST/board/", "/projects/TST/backlog/", "/projects/TST/reports/"):
            self.assertEqual(self.client.get(url).status_code, 200, url)


class BurndownTests(ProjectFixtureMixin, TestCase):
    def test_burndown_follows_transitions(self):
        today = timezone.localdate()
        start = today - datetime.timedelta(days=4)
        sprint = Sprint.objects.create(project=self.project, name="S1")
        a = make_issue(self.project, self.pm, story_points=5, sprint=sprint)
        b = make_issue(self.project, self.pm, story_points=3, sprint=sprint)
        for issue in (a, b):
            type(issue).objects.filter(pk=issue.pk).update(created_at=timezone.now() - datetime.timedelta(days=10))
        services.start_sprint(sprint, start, today + datetime.timedelta(days=5))
        finish(a, self.dev)
        # Pretend `a` was finished two days after the sprint started.
        when = timezone.make_aware(datetime.datetime.combine(start + datetime.timedelta(days=2), datetime.time(12)))
        Activity.objects.filter(issue=a, kind=Activity.Kind.TRANSITION).update(created_at=when)

        burn = services.burndown(sprint)
        self.assertEqual(burn["committed"], 8)
        self.assertEqual(burn["ideal"][0], 8)
        self.assertEqual(burn["ideal"][-1], 0)
        self.assertEqual(burn["actual"][:5], [8, 8, 3, 3, 3])
        self.assertIsNone(burn["actual"][-1])  # future days are not plotted
        self.assertIsNotNone(services.chart_geometry(burn))
