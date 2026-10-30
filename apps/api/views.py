from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agile import services as agile_services
from apps.core.markdown import render_markdown
from apps.agile.models import Sprint
from apps.issues import services as issue_services
from apps.issues.models import Issue
from apps.projects.permissions import can, get_project_or_404, visible_projects
from apps.testmgmt import services as test_services
from apps.testmgmt.models import TestRun

from .serializers import (
    CommentSerializer,
    CompleteSprintSerializer,
    IssueSerializer,
    MoveSerializer,
    ProjectSerializer,
    SprintSerializer,
    StartSprintSerializer,
    TestRunSerializer,
    TransitionSerializer,
    UserSerializer,
)


class ProjectScopedMixin:
    """Resolves `key` from the URL with the project permission rules (404 for non-members)."""

    def get_project(self, capability="view"):
        if not hasattr(self, "_project"):
            self._project = get_project_or_404(self.request.user, self.kwargs["key"])
        if capability != "view" and not can(self.request.user, self._project, capability):
            raise PermissionDenied()
        return self._project

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["project"] = self.get_project()
        return ctx

    def get_issue(self, capability="view"):
        project = self.get_project(capability)
        return get_object_or_404(Issue.objects.select_related("project"), project=project, number=self.kwargs["number"])


class MarkdownPreviewView(APIView):
    """Renders Markdown exactly like saved content (sanitized, issue chips, mentions)."""

    def post(self, request):
        text = request.data.get("text", "")
        if not isinstance(text, str) or len(text) > 200_000:
            return Response(
                {"error": {"code": "validation_error", "message": "Invalid text.", "details": None}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"html": str(render_markdown(text, request.user))})


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class ProjectListView(generics.ListAPIView):
    serializer_class = ProjectSerializer

    def get_queryset(self):
        return visible_projects(self.request.user)


class IssueSearchView(generics.ListAPIView):
    """
    Issues across every project the caller can see. Filters: assignee=me,
    project=KEY, q=text, status=<key>, open=true (exclude done statuses).
    """

    serializer_class = IssueSerializer

    def get_queryset(self):
        from apps.issues import workflow

        p = self.request.query_params
        projects = visible_projects(self.request.user)
        qs = Issue.objects.filter(project__in=projects).select_related("project", "epic", "parent")
        if p.get("assignee") == "me":
            qs = qs.filter(assignee=self.request.user)
        if p.get("project"):
            qs = qs.filter(project__key=p["project"].upper())
        if p.get("q"):
            qs = qs.filter(title__icontains=p["q"])
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("jql"):
            # The query language names statuses, labels and members of one project, so it needs project=KEY.
            from apps.issues.filters import apply_jql
            from apps.issues.query import QueryError

            if not p.get("project"):
                raise ValidationError({"jql": ["The query needs project=KEY as well."]})
            project = get_project_or_404(self.request.user, p["project"].upper())
            try:
                qs = apply_jql(qs.filter(project=project), p["jql"], project, self.request.user)
            except QueryError as exc:
                raise ValidationError({"jql": [str(exc)]})
        if p.get("open") in ("1", "true", "yes"):
            qs = [i for i in qs if not i.is_done]
            return sorted(qs, key=lambda i: (i.project.key, i.number))
        return qs.order_by("-updated_at", "-id")

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["project"] = None
        return ctx


class ProjectDetailView(ProjectScopedMixin, generics.RetrieveAPIView):
    serializer_class = ProjectSerializer

    def get_object(self):
        return self.get_project()


class IssueListCreateView(ProjectScopedMixin, generics.ListCreateAPIView):
    serializer_class = IssueSerializer

    def get_queryset(self):
        qs = self.get_project().issues.select_related("project", "epic", "parent").prefetch_related(
            "labels", "components", "fix_versions"
        )
        p = self.request.query_params
        for param, field in (("status", "status"), ("type", "issue_type"), ("priority", "priority")):
            if p.get(param):
                qs = qs.filter(**{field: p[param]})
        if p.get("assignee"):
            qs = qs.filter(assignee__isnull=True) if p["assignee"] == "none" else qs.filter(assignee_id=p["assignee"])
        if p.get("sprint"):
            qs = qs.filter(sprint__isnull=True) if p["sprint"] == "backlog" else qs.filter(sprint_id=p["sprint"])
        if p.get("q"):
            qs = qs.filter(title__icontains=p["q"])
        return qs.order_by("rank", "id")

    def perform_create(self, serializer):
        project = self.get_project("edit_issues")
        data = dict(serializer.validated_data)
        m2m = {k: data.pop(k, []) for k in ("labels", "components", "fix_versions")}
        serializer.instance = issue_services.create_issue(project, self.request.user, **m2m, **data)


class IssueDetailView(ProjectScopedMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = IssueSerializer

    def get_object(self):
        return self.get_issue()

    def perform_update(self, serializer):
        issue = self.get_issue("edit_issues")
        before = issue_services.snapshot(issue)
        data = dict(serializer.validated_data)
        m2m = {k: data.pop(k) for k in ("labels", "components", "fix_versions") if k in data}
        with transaction.atomic():
            for field, value in data.items():
                setattr(issue, field, value)
            issue.save()
            for field, value in m2m.items():
                getattr(issue, field).set(value)
            issue_services.record_changes(issue, self.request.user, before)
        serializer.instance = issue

    def perform_destroy(self, instance):
        self.get_project("delete_issues")
        for att in instance.attachments.all():
            att.delete()
        instance.delete()


class IssueTransitionView(ProjectScopedMixin, APIView):
    def post(self, request, key, number):
        issue = self.get_issue("edit_issues")
        ser = TransitionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        issue_services.transition_issue(issue, request.user, ser.validated_data["status"])
        return Response(IssueSerializer(issue, context={"project": issue.project}).data)


class IssueMoveView(ProjectScopedMixin, APIView):
    """Drag & drop on the Kanban board and the backlog."""

    def post(self, request, key, number):
        issue = self.get_issue("edit_issues")
        project = issue.project
        ser = MoveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        def neighbour(name):
            n = data.get(name)
            return project.issues.filter(number=n).first() if n else None

        kwargs = {"status": data.get("status"), "before": neighbour("before"), "after": neighbour("after")}
        if "sprint" in data:
            if data["sprint"] is None:
                kwargs["sprint"] = None
            else:
                if not can(request.user, project, "edit_issues"):
                    raise PermissionDenied()
                sprint = get_object_or_404(Sprint, pk=data["sprint"], project=project)
                if sprint.state == Sprint.State.CLOSED:
                    return Response(
                        {"error": {"code": "conflict", "message": "Cannot move issues into a closed sprint.", "details": None}},
                        status=status.HTTP_409_CONFLICT,
                    )
                kwargs["sprint"] = sprint
        issue_services.move_issue(issue, request.user, **kwargs)
        issue.refresh_from_db()
        return Response(IssueSerializer(issue, context={"project": project}).data)


class CommentListCreateView(ProjectScopedMixin, generics.ListCreateAPIView):
    serializer_class = CommentSerializer
    pagination_class = None

    def get_queryset(self):
        return self.get_issue().comments.select_related("author")

    def perform_create(self, serializer):
        issue = self.get_issue("comment")
        serializer.instance = issue_services.add_comment(issue, self.request.user, serializer.validated_data["body"])


class SprintListCreateView(ProjectScopedMixin, generics.ListCreateAPIView):
    serializer_class = SprintSerializer
    pagination_class = None

    def get_queryset(self):
        return self.get_project().sprints.all()

    def perform_create(self, serializer):
        serializer.save(project=self.get_project("manage_sprints"))


class SprintDetailView(ProjectScopedMixin, generics.RetrieveUpdateAPIView):
    serializer_class = SprintSerializer

    def get_object(self):
        capability = "view" if self.request.method == "GET" else "manage_sprints"
        return get_object_or_404(Sprint, pk=self.kwargs["pk"], project=self.get_project(capability))


class SprintStartView(ProjectScopedMixin, APIView):
    def post(self, request, key, pk):
        sprint = get_object_or_404(Sprint, pk=pk, project=self.get_project("manage_sprints"))
        ser = StartSprintSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        agile_services.start_sprint(sprint, ser.validated_data.get("start_date"), ser.validated_data.get("end_date"))
        return Response(SprintSerializer(sprint).data)


class SprintCompleteView(ProjectScopedMixin, APIView):
    def post(self, request, key, pk):
        project = self.get_project("manage_sprints")
        sprint = get_object_or_404(Sprint, pk=pk, project=project)
        ser = CompleteSprintSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        move_to = None
        if ser.validated_data.get("move_to"):
            move_to = get_object_or_404(Sprint, pk=ser.validated_data["move_to"], project=project)
        moved = agile_services.complete_sprint(sprint, move_to)
        data = SprintSerializer(sprint).data
        data["moved_issues"] = moved
        return Response(data)


class SprintBurndownView(ProjectScopedMixin, APIView):
    def get(self, request, key, pk):
        sprint = get_object_or_404(Sprint, pk=pk, project=self.get_project())
        burn = agile_services.burndown(sprint)
        if burn is None:
            return Response({"days": [], "ideal": [], "actual": [], "committed": 0, "scope": 0})
        burn["days"] = [d.isoformat() for d in burn["days"]]
        return Response(burn)


class VelocityView(ProjectScopedMixin, APIView):
    def get(self, request, key):
        vel = agile_services.velocity(self.get_project())
        return Response(
            {
                "average": vel["average"],
                "sprints": [
                    {"id": r["sprint"].pk, "name": r["sprint"].name, "committed": r["committed"], "completed": r["completed"]}
                    for r in vel["rows"]
                ],
            }
        )


class TestRunUpdateView(ProjectScopedMixin, generics.RetrieveUpdateAPIView):
    serializer_class = TestRunSerializer
    http_method_names = ["get", "patch"]

    def get_object(self):
        capability = "view" if self.request.method == "GET" else "execute_tests"
        project = self.get_project(capability)
        return get_object_or_404(TestRun.objects.select_related("test__project"), pk=self.kwargs["pk"], execution__project=project)

    def perform_update(self, serializer):
        run = self.get_object()
        serializer.instance = test_services.record_result(
            run, self.request.user, serializer.validated_data["status"], serializer.validated_data.get("comment")
        )


class CoverageView(ProjectScopedMixin, APIView):
    def get(self, request, key):
        report = test_services.coverage_report(self.get_project())
        return Response(
            {
                "total": report["total"],
                "covered_percent": report["covered_percent"],
                "totals": [{k: str(v) if k == "label" else v for k, v in t.items()} for t in report["totals"]],
                "requirements": [
                    {
                        "key": r["issue"].key,
                        "title": r["issue"].title,
                        "status": r["status"],
                        "tests": [
                            {"key": t.key, "latest": run.status if run else None} for t, run in r["tests"]
                        ],
                    }
                    for r in report["rows"]
                ],
            }
        )


def _execution_summary(execution):
    counts = execution.summary()
    return {
        "id": execution.pk,
        "name": execution.name,
        "environment": execution.environment,
        "plan_id": execution.plan_id,
        "plan_name": execution.plan.name if execution.plan_id else None,
        "run_state": execution.run_state,
        "run_requested_at": execution.run_requested_at,
        "run_finished_at": execution.run_finished_at,
        "created_at": execution.created_at,
        "counts": {k: counts[k] for k in ("total", "todo", "pass", "fail", "blocked", "skipped", "na", "executed")},
    }


class TestExecutionListCreateView(ProjectScopedMixin, APIView):
    """Test executions of a project. ?state=queued lists the ones the runner should pick up."""

    def get(self, request, key):
        project = self.get_project()
        qs = project.test_executions.select_related("plan").order_by("-created_at")
        if request.query_params.get("state"):
            qs = qs.filter(run_state=request.query_params["state"])
        return Response([_execution_summary(e) for e in qs[:100]])

    def post(self, request, key):
        from apps.testmgmt import services as test_services
        from apps.testmgmt.models import TestPlan

        project = self.get_project("manage_tests")
        name = (request.data.get("name") or "").strip()
        if not name:
            raise ValidationError({"name": ["Το όνομα είναι υποχρεωτικό."]})
        plan = None
        if request.data.get("plan"):
            plan = get_object_or_404(TestPlan, pk=request.data["plan"], project=project)
        # Optional list of test keys ("SPT-81"): runs for exactly these tests, with or without a plan.
        keys = request.data.get("tests") or []
        if not isinstance(keys, list):
            raise ValidationError({"tests": ["Αναμένεται λίστα κλειδιών, π.χ. [\"SPT-81\"]."]})
        numbers = []
        for item in keys:
            prefix, _, number = str(item).upper().rpartition("-")
            if prefix != project.key or not number.isdigit():
                raise ValidationError({"tests": [f"Μη έγκυρο κλειδί: {item}"]})
            numbers.append(int(number))
        tests = Issue.objects.filter(project=project, number__in=numbers)
        execution = test_services.create_execution(
            project,
            request.user,
            name=name,
            plan=plan,
            tests=tests,
            environment=request.data.get("environment", "") or "",
        )
        return Response(_execution_summary(execution), status=status.HTTP_201_CREATED)


class TestExecutionDetailView(ProjectScopedMixin, APIView):
    """One execution with its runs. PATCH {run_state: queued|running|done} for the runner."""

    def _execution(self, key, pk, capability="view"):
        from apps.testmgmt.models import TestExecution

        project = self.get_project(capability)
        return get_object_or_404(TestExecution.objects.select_related("plan"), pk=pk, project=project)

    def get(self, request, key, pk):
        execution = self._execution(key, pk)
        runs = []
        for run in execution.runs.select_related("test").order_by("test__number"):
            test = run.test
            runs.append(
                {
                    "run_id": run.pk,
                    "test_key": test.key,
                    "title": test.title,
                    "status": run.status,
                    "comment": run.comment,
                    "automation": (test.custom_fields or {}).get("automation", ""),
                    "steps": [
                        {"order": s.order, "action": s.action, "data": s.data, "expected": s.expected_result}
                        for s in test.test_steps.all()
                    ],
                    "executed_at": run.executed_at,
                }
            )
        data = _execution_summary(execution)
        data["runs"] = runs
        return Response(data)

    def patch(self, request, key, pk):
        from apps.testmgmt import services as test_services

        execution = self._execution(key, pk, "manage_tests")
        state = request.data.get("run_state")
        if state not in ("idle", "queued", "running", "done"):
            raise ValidationError({"run_state": ["Μη έγκυρη τιμή."]})
        execution = test_services.set_run_state(execution, state)
        return Response(_execution_summary(execution))


class IssueLinkCreateView(ProjectScopedMixin, APIView):
    """POST {target: "SPT-12", link_type: "tests|relates|blocks|duplicates"} from the issue in the URL."""

    def post(self, request, key, number):
        from apps.issues import services as issue_services
        from apps.issues.models import IssueLink

        issue = self.get_issue("edit_issues")
        target_key = (request.data.get("target") or "").strip().upper()
        link_type = request.data.get("link_type", "")
        if link_type not in IssueLink.LinkType.values:
            raise ValidationError({"link_type": ["Μη έγκυρος τύπος σύνδεσης."]})
        try:
            tkey, tnum = target_key.rsplit("-", 1)
            target = Issue.objects.select_related("project").get(project__key=tkey, number=int(tnum))
        except (ValueError, Issue.DoesNotExist):
            raise ValidationError({"target": [f"Δεν βρέθηκε το {target_key}."]})
        if not can(request.user, target.project, "view"):
            raise ValidationError({"target": [f"Δεν βρέθηκε το {target_key}."]})
        try:
            issue_services.link_issues(issue, target, link_type, request.user)
        except issue_services.WorkflowError as exc:
            raise ValidationError({"link_type": [str(exc)]})
        return Response({"source": issue.key, "target": target.key, "link_type": link_type}, status=201)
