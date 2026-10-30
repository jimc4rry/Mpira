import re

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import cache_control, never_cache
from django.views.decorators.http import require_POST

from apps.issues import workflow
from apps.issues.models import Activity, Issue
from apps.projects.permissions import visible_projects
from apps.wiki.models import Space
from apps.wiki.services import search_pages

from .models import Notification

FAVICON_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
    "<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'>"
    "<stop offset='0' stop-color='#3b6cff'/><stop offset='1' stop-color='#8b5cf6'/></linearGradient></defs>"
    "<rect width='100' height='100' rx='24' fill='url(#g)'/>"
    "<text x='50' y='70' font-family='Arial' font-weight='900' font-size='60' text-anchor='middle' fill='white'>M</text>"
    "</svg>"
)


@cache_control(max_age=86400)
def favicon(request):
    """The brand mark for browsers that ask for /favicon.ico. Pages carry the same icon inline."""
    return HttpResponse(FAVICON_SVG, content_type="image/svg+xml")

ISSUE_KEY_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9]{1,9})-(\d+)\s*$")


@never_cache
def healthz(request):
    """Liveness + DB check for Railway's healthcheck (see railway.json)."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # noqa: BLE001 - any DB failure means unhealthy
        return JsonResponse({"status": "error", "database": "unreachable"}, status=503)
    return JsonResponse({"status": "ok", "database": "ok"})


@login_required
def dashboard(request):
    projects = visible_projects(request.user)
    # Done-ness is per project, so filter in Python after a bounded query.
    my_issues = [
        i
        for i in Issue.objects.filter(assignee=request.user, project__in=projects)
        .select_related("project")
        .order_by("-updated_at")[:200]
        if not i.is_done
    ][:15]
    reported = [
        i
        for i in Issue.objects.filter(reporter=request.user, project__in=projects)
        .select_related("project")
        .order_by("-created_at")[:100]
        if not i.is_done
    ][:8]
    activity = (
        Activity.objects.filter(issue__project__in=projects)
        .select_related("issue__project", "actor")
        .order_by("-created_at")[:20]
    )
    return render(
        request,
        "core/dashboard.html",
        {
            "projects": projects,
            "my_issues": my_issues,
            "reported": reported,
            "activity": activity,
            "notifications": request.user.notifications.select_related("actor")[:8],
        },
    )


@login_required
def notifications(request):
    items = request.user.notifications.select_related("actor")[:100]
    return render(request, "core/notifications.html", {"items": items})


@login_required
def notification_open(request, pk):
    n = get_object_or_404(Notification, pk=pk, recipient=request.user)
    if not n.is_read:
        n.is_read = True
        n.save(update_fields=["is_read"])
    target = n.target_url
    if not url_has_allowed_host_and_scheme(target, {request.get_host()}):
        target = "/"
    return redirect(target)


@login_required
@require_POST
def notifications_mark_all(request):
    request.user.notifications.filter(is_read=False).update(is_read=True)
    return redirect("core:notifications")


@login_required
def search(request):
    q = request.GET.get("q", "").strip()
    projects = visible_projects(request.user)
    m = ISSUE_KEY_RE.match(q)
    if m:
        issue = Issue.objects.filter(
            project__in=projects, project__key=m.group(1).upper(), number=int(m.group(2))
        ).first()
        if issue:
            return redirect(issue.get_absolute_url())
    issues, pages = [], []
    if q:
        issues = (
            Issue.objects.filter(project__in=projects)
            .filter(Q(title__icontains=q) | Q(description__icontains=q))
            .select_related("project", "assignee")
            .order_by("-updated_at")[:50]
        )
        pages = search_pages(Space.objects.filter(project__in=projects), q)[:30]
    return render(request, "core/search.html", {"q": q, "issues": issues, "pages": pages})


def error_404(request, exception=None):
    return render(request, "core/error.html", {"code": 404}, status=404)


def error_403(request, exception=None):
    return render(request, "core/error.html", {"code": 403}, status=403)


def error_500(request):
    return render(request, "core/error.html", {"code": 500}, status=500)


@login_required
def help_page(request):
    base = request.build_absolute_uri("/").rstrip("/")
    return render(
        request,
        "core/help.html",
        {"base_url": base, "api_base": f"{base}/api/v1/"},
    )
