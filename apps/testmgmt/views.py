from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.issues.models import REQUIREMENT_TYPES, Issue, IssueLink, IssueType
from apps.projects.permissions import get_project_or_404, visible_projects
from apps.projects.views import project_context

from . import services
from .forms import TestExecutionForm, TestPlanForm, TestStepFormSet
from .models import RunStatus, TestExecution, TestPlan, TestRun


def issue_test_panel(issue, user):
    """Extra context for the issue detail page (Test or requirement)."""
    visible = visible_projects(user)
    if issue.issue_type == IssueType.TEST:
        covers = [
            link.target
            for link in issue.outward_links.filter(
                link_type=IssueLink.LinkType.TESTS, target__project__in=visible
            ).select_related("target__project")
        ]
        runs = issue.test_runs.exclude(status=RunStatus.TODO).select_related("execution", "executed_by").order_by("-executed_at")[:20]
        return {"is_test": True, "test_steps": issue.test_steps.all(), "covers": covers, "test_runs": runs}
    if issue.issue_type in REQUIREMENT_TYPES:
        tests = [
            link.source
            for link in issue.inward_links.filter(
                link_type=IssueLink.LinkType.TESTS, source__project__in=visible
            ).select_related("source__project")
        ]
        latest = services.latest_results([t.pk for t in tests])
        status = services.requirement_status([t.pk for t in tests], latest)
        return {
            "is_requirement": True,
            "covering_tests": [(t, latest.get(t.pk)) for t in tests],
            "coverage_status": status,
            "coverage_label": services.Coverage.LABELS[status],
        }
    return {}


@login_required
def test_steps(request, key, number):
    project = get_project_or_404(request.user, key, "manage_tests")
    test = get_object_or_404(Issue, project=project, number=number, issue_type=IssueType.TEST)
    formset = TestStepFormSet(request.POST or None, queryset=test.test_steps.all())
    if request.method == "POST" and formset.is_valid():
        steps = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        start = test.test_steps.count()
        for i, step in enumerate(steps):
            step.test = test
            if not step.pk:
                step.order = start + i + 1
            step.save()
        for i, step in enumerate(test.test_steps.all(), start=1):
            if step.order != i:
                step.order = i
                step.save(update_fields=["order"])
        messages.success(request, _("Test steps saved."))
        return redirect(test.get_absolute_url())
    return render(request, "testmgmt/test_steps.html", project_context(request, project, test=test, formset=formset))


@login_required
def plan_list(request, key):
    project = get_project_or_404(request.user, key)
    plans = project.test_plans.prefetch_related("tests")
    return render(request, "testmgmt/plan_list.html", project_context(request, project, plans=plans))


@login_required
def plan_form(request, key, pk=None):
    project = get_project_or_404(request.user, key, "manage_tests")
    plan = get_object_or_404(TestPlan, pk=pk, project=project) if pk else TestPlan(project=project)
    form = TestPlanForm(request.POST or None, instance=plan, project=project)
    if request.method == "POST":
        if pk and request.POST.get("delete"):
            plan.delete()
            messages.success(request, _("Test plan deleted."))
            return redirect("testmgmt:plan_list", key=project.key)
        if form.is_valid():
            plan = form.save(commit=False)
            plan.project = project
            if not plan.pk:
                plan.created_by = request.user
            plan.save()
            form.save_m2m()
            messages.success(request, _("Test plan saved."))
            return redirect(plan.get_absolute_url())
    return render(request, "testmgmt/plan_form.html", project_context(request, project, form=form, plan=plan))


@login_required
def plan_detail(request, key, pk):
    project = get_project_or_404(request.user, key)
    plan = get_object_or_404(TestPlan, pk=pk, project=project)
    tests = list(plan.tests.select_related("project").order_by("number"))
    latest = services.latest_results([t.pk for t in tests])
    rows = [(t, latest.get(t.pk)) for t in tests]
    counts = {s: 0 for s in RunStatus.values}
    for _t, run in rows:
        counts[run.status if run else RunStatus.TODO] += 1
    return render(
        request,
        "testmgmt/plan_detail.html",
        project_context(
            request,
            project,
            plan=plan,
            rows=rows,
            counts=counts,
            executions=plan.executions.all(),
        ),
    )


@login_required
def execution_list(request, key):
    project = get_project_or_404(request.user, key)
    executions = project.test_executions.select_related("plan", "fix_version", "created_by")
    return render(
        request,
        "testmgmt/execution_list.html",
        project_context(request, project, executions=[(e, e.summary()) for e in executions]),
    )


@login_required
def execution_create(request, key):
    project = get_project_or_404(request.user, key, "manage_tests")
    initial = {}
    if (request.GET.get("plan") or "").isdigit():
        plan = project.test_plans.filter(pk=int(request.GET["plan"])).first()
        if plan:
            initial = {"plan": plan, "name": f"{plan.name} – {_('run')}", "fix_version": plan.fix_version}
    form = TestExecutionForm(request.POST or None, project=project, initial=initial)
    if request.method == "POST" and form.is_valid():
        execution = services.create_execution(
            project,
            request.user,
            name=form.cleaned_data["name"],
            plan=form.cleaned_data["plan"],
            tests=form.cleaned_data["tests"],
            environment=form.cleaned_data["environment"],
            fix_version=form.cleaned_data["fix_version"],
        )
        messages.success(request, _("Test execution created."))
        return redirect(execution.get_absolute_url())
    return render(request, "testmgmt/execution_form.html", project_context(request, project, form=form))


@login_required
def execution_detail(request, key, pk):
    project = get_project_or_404(request.user, key)
    execution = get_object_or_404(TestExecution.objects.select_related("plan", "fix_version"), pk=pk, project=project)
    runs = execution.runs.select_related("test__project", "executed_by").prefetch_related("test__test_steps")
    return render(
        request,
        "testmgmt/execution_detail.html",
        project_context(
            request,
            project,
            execution=execution,
            runs=runs,
            summary=execution.summary(),
            run_statuses=RunStatus.choices,
        ),
    )


@login_required
@require_POST
def execution_delete(request, key, pk):
    project = get_project_or_404(request.user, key, "manage_tests")
    execution = get_object_or_404(TestExecution, pk=pk, project=project)
    execution.delete()
    messages.success(request, _("Test execution deleted."))
    return redirect("testmgmt:execution_list", key=project.key)


@login_required
@require_POST
def run_update(request, key, pk):
    """Non-JS fallback for recording a result (the page normally uses the API)."""
    project = get_project_or_404(request.user, key, "execute_tests")
    run = get_object_or_404(TestRun, pk=pk, execution__project=project)
    status = request.POST.get("status")
    if status in RunStatus.values:
        services.record_result(run, request.user, status, request.POST.get("comment"))
    return redirect(run.execution.get_absolute_url() + f"#run-{run.pk}")


@login_required
def coverage(request, key):
    project = get_project_or_404(request.user, key)
    version = None
    if (request.GET.get("version") or "").isdigit():
        version = project.versions.filter(pk=int(request.GET["version"])).first()
    report = services.coverage_report(project, version)
    return render(
        request,
        "testmgmt/coverage.html",
        project_context(request, project, report=report, versions=project.versions.all(), version=version),
    )


@login_required
@require_POST
def execution_run_queue(request, key, pk):
    """Queue this execution for the automated runner (the run starts on the runner's machine)."""
    project = get_project_or_404(request.user, key, "execute_tests")
    execution = get_object_or_404(TestExecution, pk=pk, project=project)
    try:
        services.request_automated_run(execution, request.user)
        messages.success(request, _("Η εκτέλεση μπήκε στην ουρά του αυτοματοποιημένου runner."))
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect(execution.get_absolute_url())
