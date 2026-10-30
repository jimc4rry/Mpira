"""
Demo data: 4 users, one project (MPR) with epics/stories/bugs/tests, two
closed sprints + one active + one future (so burndown and velocity have
something to show), a wiki space with linked pages, and a test plan with an
execution. Idempotent: does nothing if project MPR already exists, unless
--reset is passed.

    python manage.py seed_demo                      # dev: uses DEMO_PASSWORD or the dev default
    python manage.py seed_demo --password 'S3cret!'  # required in production
"""

import datetime
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.agile import services as agile
from apps.agile.models import Sprint
from apps.issues import services as issues
from apps.issues.models import Activity, CustomFieldDefinition, IssueLink, IssueType, Priority, Status
from apps.projects.models import Component, Label, Project, ProjectMembership, ProjectRole, Version
from apps.testmgmt import services as tests
from apps.testmgmt.models import RunStatus, TestPlan, TestStep
from apps.wiki import services as wiki
from apps.wiki.models import Page, Space

DEV_DEFAULT_PASSWORD = "mpira-demo-2026"

USERS = [
    ("admin@mpira.local", "admin", "Alex", "Admin", Role.ADMIN, None),
    ("maria@mpira.local", "maria", "Maria", "Papadopoulou", Role.PROJECT_MANAGER, ProjectRole.PROJECT_MANAGER),
    ("nikos@mpira.local", "nikos", "Nikos", "Georgiou", Role.DEVELOPER, ProjectRole.DEVELOPER),
    ("eleni@mpira.local", "eleni", "Eleni", "Konstantinou", Role.TESTER, ProjectRole.TESTER),
]

STEPS_TO = {
    Status.TODO: [],
    Status.IN_PROGRESS: [Status.IN_PROGRESS],
    Status.IN_REVIEW: [Status.IN_PROGRESS, Status.IN_REVIEW],
    Status.DONE: [Status.IN_PROGRESS, Status.IN_REVIEW, Status.DONE],
}


def days_ago(n, hour=10):
    d = timezone.localdate() - datetime.timedelta(days=n)
    return timezone.make_aware(datetime.datetime.combine(d, datetime.time(hour, 0)))


class Command(BaseCommand):
    help = "Create demo users, a demo project (MPR) with sprints, wiki pages and tests."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Password for all demo users (or set DEMO_PASSWORD).")
        parser.add_argument("--reset", action="store_true", help="Delete project MPR first and re-create it.")

    def handle(self, *args, **opts):
        password = opts.get("password") or os.environ.get("DEMO_PASSWORD")
        if not password:
            if not settings.DEBUG:
                raise CommandError("In production pass --password or set DEMO_PASSWORD.")
            password = DEV_DEFAULT_PASSWORD

        if opts["reset"]:
            Project.objects.filter(key="MPR").delete()
        if Project.objects.filter(key="MPR").exists():
            self.stdout.write(self.style.WARNING("Project MPR already exists - nothing to do (use --reset)."))
            return

        with transaction.atomic():
            users = self._users(password)
            self._project(users)
        self.stdout.write(self.style.SUCCESS("Demo data created."))
        self.stdout.write("Log in with any of: " + ", ".join(u[0] for u in USERS))
        if password == DEV_DEFAULT_PASSWORD:
            self.stdout.write(f"Password (dev default): {DEV_DEFAULT_PASSWORD}")

    # ------------------------------------------------------------------ users
    def _users(self, password):
        out = {}
        for email, handle, first, last, role, _prole in USERS:
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(
                    username=handle, email=email, password=password, first_name=first, last_name=last, role=role
                )
                if role == Role.ADMIN:
                    user.is_staff = user.is_superuser = True
                    user.save()
            out[handle] = user
        return out

    # ---------------------------------------------------------------- helpers
    def _advance(self, issue, user, target, when):
        """Walk the workflow to `target`, back-dating each transition to `when` (list of days-ago)."""
        order = list(STEPS_TO)
        steps = [s for s in STEPS_TO[target] if order.index(s) > order.index(Status(issue.status))]
        for i, status in enumerate(steps):
            issues.transition_issue(issue, user, status)
            ts = days_ago(when[min(i, len(when) - 1)], hour=11 + i)
            last = Activity.objects.filter(issue=issue, kind=Activity.Kind.TRANSITION).order_by("-id").first()
            Activity.objects.filter(pk=last.pk).update(created_at=ts)
            if status == Status.DONE:
                type(issue).objects.filter(pk=issue.pk).update(resolved_at=ts)

    # ---------------------------------------------------------------- project
    def _project(self, u):
        pm, dev, qa, admin = u["maria"], u["nikos"], u["eleni"], u["admin"]
        project = Project.objects.create(
            key="MPR",
            name="Mpira Demo – Webshop",
            description="Demo project: a small e-shop team planning the **1.1 release**. Explore the board, backlog, reports, wiki and tests.",
            lead=pm,
        )
        for email, handle, *_rest, prole in USERS:
            if prole:
                ProjectMembership.objects.create(project=project, user=u[handle], role=prole)

        comp = {n: Component.objects.create(project=project, name=n) for n in ["Frontend", "Backend", "Payments"]}
        v10 = Version.objects.create(project=project, name="1.0", status=Version.Status.RELEASED, release_date=timezone.localdate() - datetime.timedelta(days=30))
        v11 = Version.objects.create(project=project, name="1.1", release_date=timezone.localdate() + datetime.timedelta(days=21))
        lab = {
            n: Label.objects.create(project=project, name=n, color=c)
            for n, c in [("ux", "#8b5cf6"), ("performance", "#f59e0b"), ("security", "#ef4444"), ("tech-debt", "#64748b")]
        }
        CustomFieldDefinition.objects.create(
            project=project, name="Customer impact", key="customer_impact", field_type="select",
            options="Low, Medium, High", issue_type=IssueType.BUG, position=1,
        )
        CustomFieldDefinition.objects.create(
            project=project, name="Browser / environment", key="environment", field_type="text", issue_type=IssueType.BUG, position=2
        )
        CustomFieldDefinition.objects.create(
            project=project, name="UX reviewed", key="ux_reviewed", field_type="checkbox", issue_type=IssueType.STORY, position=3
        )

        def mk(issue_type, title, *, points=None, epic=None, assignee=None, priority=Priority.MEDIUM, labels=(), components=(),
               description="", parent=None, custom=None, versions=(v11,), reporter=pm):
            issue = issues.create_issue(
                project, reporter, issue_type=issue_type, title=title, story_points=points, epic=epic, assignee=assignee,
                priority=priority, description=description, parent=parent, custom_fields=custom or {},
                labels=[lab[x] for x in labels], components=[comp[x] for x in components],
                fix_versions=list(versions) if issue_type != IssueType.EPIC else [],
            )
            type(issue).objects.filter(pk=issue.pk).update(created_at=days_ago(45))
            Activity.objects.filter(issue=issue, kind=Activity.Kind.CREATED).update(created_at=days_ago(45))
            return issue

        # Epics
        e_checkout = mk(IssueType.EPIC, "Checkout redesign", description="One-page checkout with saved cards and clearer shipping costs.")
        e_accounts = mk(IssueType.EPIC, "Customer accounts", description="Sign-up, login, order history and saved addresses.")
        e_perf = mk(IssueType.EPIC, "Performance", description="Get product pages under 1s LCP on 4G.")

        # Sprint 1 & 2 (closed), 3 (active), 4 (future)
        s1 = Sprint.objects.create(project=project, name="MPR Sprint 1", goal="Customer accounts MVP")
        s2 = Sprint.objects.create(project=project, name="MPR Sprint 2", goal="Order history and first checkout pieces")
        s3 = Sprint.objects.create(project=project, name="MPR Sprint 3", goal="Ship the new checkout behind a feature flag")
        s4 = Sprint.objects.create(project=project, name="MPR Sprint 4", goal="Performance pass before 1.1")

        # --- Sprint 1 content
        a1 = mk(IssueType.STORY, "Sign up with email and password", points=5, epic=e_accounts, assignee=dev, components=["Backend"], versions=(v10,))
        a2 = mk(IssueType.STORY, "Log in / log out", points=3, epic=e_accounts, assignee=dev, components=["Backend", "Frontend"], versions=(v10,))
        a3 = mk(IssueType.STORY, "Password reset by email", points=3, epic=e_accounts, assignee=dev, labels=["security"], versions=(v10,))
        a4 = mk(IssueType.TASK, "Set up transactional email provider", points=2, epic=e_accounts, assignee=pm, versions=(v10,))
        a5 = mk(IssueType.STORY, "Saved addresses", points=5, epic=e_accounts, assignee=dev, components=["Frontend"])
        for i in (a1, a2, a3, a4, a5):
            i.sprint = s1
            i.save(update_fields=["sprint"])
        agile.start_sprint(s1, (timezone.localdate() - datetime.timedelta(days=38)), timezone.localdate() - datetime.timedelta(days=25))
        self._advance(a4, pm, Status.DONE, [37, 36, 35])
        self._advance(a1, dev, Status.DONE, [37, 33, 32])
        self._advance(a2, dev, Status.DONE, [33, 30, 29])
        self._advance(a3, dev, Status.DONE, [30, 27, 26])
        self._advance(a5, dev, Status.IN_PROGRESS, [27])
        agile.complete_sprint(s1, move_to=s2)
        Sprint.objects.filter(pk=s1.pk).update(started_at=days_ago(38, 9), completed_at=days_ago(25, 17))
        s2.refresh_from_db()

        # --- Sprint 2 content
        b1 = mk(IssueType.STORY, "Order history page", points=5, epic=e_accounts, assignee=dev, components=["Frontend"], custom={"ux_reviewed": True})
        b2 = mk(IssueType.STORY, "Cart summary component", points=3, epic=e_checkout, assignee=dev, labels=["ux"], components=["Frontend"])
        b3 = mk(IssueType.BUG, "Totals are rounded wrongly for 3+ items", points=2, epic=e_checkout, assignee=dev, priority=Priority.HIGH,
                components=["Backend"], custom={"customer_impact": "High", "environment": "All browsers"},
                description="Steps:\n1. Add 3 items at 3.333 €\n2. Total shows 9.99 instead of 10.00")
        b4 = mk(IssueType.TASK, "Extract price formatting helper", points=1, epic=e_checkout, assignee=dev, labels=["tech-debt"])
        for i in (b1, b2, b3, b4):
            i.sprint = s2
            i.save(update_fields=["sprint"])
        agile.start_sprint(s2, timezone.localdate() - datetime.timedelta(days=24), timezone.localdate() - datetime.timedelta(days=11))
        self._advance(a5, dev, Status.DONE, [22, 21])  # carried over from Sprint 1 (already In Progress)
        self._advance(b4, dev, Status.DONE, [23, 22, 21])
        self._advance(b3, dev, Status.DONE, [22, 20, 19])
        self._advance(b1, dev, Status.DONE, [20, 16, 14])
        self._advance(b2, dev, Status.IN_REVIEW, [16, 12])
        agile.complete_sprint(s2, move_to=s3)
        Sprint.objects.filter(pk=s2.pk).update(started_at=days_ago(24, 9), completed_at=days_ago(11, 17))
        s3.refresh_from_db()

        # --- Sprint 3 (active)
        c1 = mk(IssueType.STORY, "One-page checkout layout", points=8, epic=e_checkout, assignee=dev, labels=["ux"], components=["Frontend"],
                description="Replace the 4-step wizard with a single page. Design notes live in the wiki: see *Checkout redesign*.")
        c2 = mk(IssueType.STORY, "Pay with saved card", points=5, epic=e_checkout, assignee=dev, labels=["security"], components=["Payments"])
        c3 = mk(IssueType.STORY, "Show shipping cost before payment", points=3, epic=e_checkout, assignee=pm, components=["Frontend", "Backend"])
        c4 = mk(IssueType.BUG, "Coupon field accepts expired codes", points=2, epic=e_checkout, assignee=dev, priority=Priority.HIGHEST,
                components=["Backend"], custom={"customer_impact": "Medium", "environment": "Production"})
        c5 = mk(IssueType.TASK, "Feature flag for new checkout", points=1, epic=e_checkout, assignee=dev)
        for i in (c1, c2, c3, c4, c5):
            i.sprint = s3
            i.save(update_fields=["sprint"])
        agile.start_sprint(s3, timezone.localdate() - datetime.timedelta(days=6), timezone.localdate() + datetime.timedelta(days=7))
        Sprint.objects.filter(pk=s3.pk).update(started_at=days_ago(6, 9))
        self._advance(c5, dev, Status.DONE, [6, 5, 5])
        self._advance(b2, dev, Status.DONE, [5])  # was In Review, carried over
        self._advance(c4, dev, Status.IN_REVIEW, [5, 3])
        self._advance(c1, dev, Status.IN_PROGRESS, [4])
        st1 = mk(IssueType.SUBTASK, "Mobile layout for checkout", parent=c1, assignee=dev)
        st1.sprint = s3
        st1.save(update_fields=["sprint"])
        st2 = mk(IssueType.SUBTASK, "Address autocomplete", parent=c1, assignee=dev)
        st2.sprint = s3
        st2.save(update_fields=["sprint"])
        self._advance(st1, dev, Status.DONE, [3, 2, 2])

        # --- Sprint 4 (future) + backlog
        d1 = mk(IssueType.STORY, "Lazy-load product images", points=3, epic=e_perf, labels=["performance"], components=["Frontend"])
        d2 = mk(IssueType.TASK, "Add CDN caching headers", points=2, epic=e_perf, labels=["performance"], components=["Backend"], assignee=dev)
        for i in (d1, d2):
            i.sprint = s4
            i.save(update_fields=["sprint"])
        mk(IssueType.STORY, "Wishlist", points=8, epic=e_accounts, priority=Priority.LOW)
        mk(IssueType.BUG, "Footer overlaps cookie banner on iPhone SE", points=1, priority=Priority.LOW, labels=["ux"],
           custom={"customer_impact": "Low", "environment": "Safari iOS 17"})
        mk(IssueType.STORY, "Guest checkout", points=5, epic=e_checkout)
        mk(IssueType.TASK, "Upgrade payment SDK", points=2, labels=["security", "tech-debt"], components=["Payments"])

        # --- Comments & mentions
        issues.add_comment(c2, pm, "@nikos let's reuse the tokenisation flow from the PSP sandbox. @eleni please prepare test cards.")
        issues.add_comment(c2, dev, "Agreed - see [[MPR-%d]] for the rounding fix this depends on." % b3.number)
        issues.add_comment(c4, qa, "Reproduced on staging with code `SUMMER23`. Expired 2023-09-01.")
        issues.link_issues(c4, c2, IssueLink.LinkType.BLOCKS, pm)

        # --- Tests (Xray-style)
        def test_case(title, steps, covers):
            t = mk(IssueType.TEST, title, assignee=qa, reporter=qa)
            for n, (action, data, expected) in enumerate(steps, start=1):
                TestStep.objects.create(test=t, order=n, action=action, data=data, expected_result=expected)
            for req in covers:
                issues.link_issues(t, req, IssueLink.LinkType.TESTS, qa)
            return t

        t1 = test_case("Checkout with saved card", [
            ("Log in as a customer with a saved card", "customer@example.com", "Logged in, cart visible"),
            ("Open checkout and pick the saved card", "", "Card ending 4242 is preselected"),
            ("Pay", "", "Order confirmation page is shown"),
        ], [c2])
        t2 = test_case("Expired coupon is rejected", [
            ("Add any product to the cart", "", "Cart has 1 item"),
            ("Apply coupon", "SUMMER23", "Error: 'This code has expired'"),
        ], [c4])
        t3 = test_case("Totals for 3 items at 3.333 €", [
            ("Add 3 items priced 3.333 €", "", "Cart total is 10.00 €"),
        ], [b3])
        t4 = test_case("Shipping cost visible before payment", [
            ("Enter a Greek address", "Athens 10558", "Shipping cost is shown in the summary"),
        ], [c3])
        t5 = test_case("Order history lists past orders", [
            ("Log in as a customer with 2 orders", "", "Both orders listed, newest first"),
        ], [b1])
        test_case("Sign up with an existing email shows an error", [
            ("Open sign up and use an existing email", "maria@mpira.local", "Friendly error, no account created"),
        ], [a1])

        plan = TestPlan.objects.create(project=project, name="Release 1.1 regression", description="Everything that must pass before 1.1 ships.",
                                       fix_version=v11, created_by=qa)
        plan.tests.set([t1, t2, t3, t4, t5])
        ex = tests.create_execution(project, qa, name="1.1 RC1 – Chrome", plan=plan, environment="Staging · Chrome 129", fix_version=v11)
        results = {t1.pk: RunStatus.PASS, t2.pk: RunStatus.FAIL, t3.pk: RunStatus.PASS, t5.pk: RunStatus.BLOCKED}
        for run in ex.runs.all():
            if run.test_id in results:
                comment = "Coupon still accepted on staging" if results[run.test_id] == RunStatus.FAIL else ""
                if results[run.test_id] == RunStatus.BLOCKED:
                    comment = "Test account has no orders on staging"
                tests.record_result(run, qa, results[run.test_id], comment)

        # --- Wiki
        space = Space.objects.get(project=project)
        space.description = "Team handbook for the webshop."
        space.save()

        def page(title, body, parent=None, author=pm):
            p, _changed = wiki.save_page(Page(space=space, position=space.pages.count()), author, title=title, body=body,
                                         parent=parent, change_note="Created")
            return p

        home = page("Team handbook", f"""# Welcome 👋

This is the **Mpira demo** space for the webshop team.

## Current focus
- Sprint goal: *ship the new checkout behind a feature flag*
- Epic: [[MPR-{e_checkout.number}]]
- Top risk: [[MPR-{c4.number}]]

## Pages
Use the tree on the left. Mention a teammate with @maria or @nikos.
""")
        page("Definition of Done", """- Code reviewed and merged to `main`
- Acceptance criteria met
- Tests linked to the story and **passing** in the latest execution
- Docs/wiki updated if behaviour changed
""", parent=home)
        design = page("Checkout redesign", f"""## Goals
1. Fewer steps → higher conversion
2. Show total cost (incl. shipping) **before** payment — [[MPR-{c3.number}]]

## Decisions
| Topic | Decision |
|---|---|
| Layout | Single page, sticky summary on desktop |
| Saved cards | PSP tokens only, never PANs — [[MPR-{c2.number}]] |

```text
/checkout  →  address · shipping · payment · review
```
""", author=dev)
        wiki.save_page(design, pm, title=design.title, body=design.body + "\n\n> Reviewed with @nikos on Monday.", parent=None,
                       change_note="Added review note")
        page("Release checklist 1.1", f"""- [ ] All issues in fix version 1.1 Done
- [ ] Regression plan executed (see *Test plans*)
- [ ] Coupon bug fixed: [[MPR-{c4.number}]]
""", parent=home, author=qa)
