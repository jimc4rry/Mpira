"""Small factories shared by every app's tests."""

import itertools

from apps.accounts.models import Role, User
from apps.issues import services as issue_services
from apps.issues import workflow
from apps.issues.models import IssueType
from apps.projects.models import Project, ProjectMembership, ProjectRole

_seq = itertools.count(1)
PASSWORD = "Str0ng-test-pass!"


def make_user(role=Role.DEVELOPER, **kwargs):
    n = next(_seq)
    kwargs.setdefault("email", f"user{n}@example.com")
    kwargs.setdefault("username", f"user{n}")
    return User.objects.create_user(password=PASSWORD, role=role, **kwargs)


def make_project(key="TST", members=(), **kwargs):
    """members: iterable of (user, ProjectRole)."""
    project = Project.objects.create(key=key, name=kwargs.pop("name", f"Project {key}"), **kwargs)
    workflow.ensure_default(project)
    for user, role in members:
        ProjectMembership.objects.create(project=project, user=user, role=role)
    return project


def make_issue(project, user, issue_type=IssueType.STORY, **fields):
    fields.setdefault("title", f"Issue {next(_seq)}")
    return issue_services.create_issue(project, user, issue_type=issue_type, **fields)


class ProjectFixtureMixin:
    """A project with one user per role."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = make_user(Role.ADMIN, email="admin@example.com", username="admin")
        cls.pm = make_user(Role.PROJECT_MANAGER, email="pm@example.com", username="pm")
        cls.dev = make_user(Role.DEVELOPER, email="dev@example.com", username="dev")
        cls.tester = make_user(Role.TESTER, email="qa@example.com", username="qa")
        cls.viewer = make_user(Role.VIEWER, email="viewer@example.com", username="viewer")
        cls.outsider = make_user(Role.DEVELOPER, email="out@example.com", username="outsider")
        cls.project = make_project(
            "TST",
            members=[
                (cls.pm, ProjectRole.PROJECT_MANAGER),
                (cls.dev, ProjectRole.DEVELOPER),
                (cls.tester, ProjectRole.TESTER),
                (cls.viewer, ProjectRole.VIEWER),
            ],
        )
