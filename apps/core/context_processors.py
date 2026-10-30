from django.conf import settings

# (namespace, url_name prefix) → sidebar section to highlight.
NAV_SECTIONS = [
    ("core", "dashboard", "dashboard"),
    ("projects", "list", "projects"),
    ("projects", "create", "projects"),
    ("projects", "detail", "overview"),
    ("projects", "", "settings"),
    ("issues", "", "issues"),
    ("agile", "board", "board"),
    ("agile", "reports", "reports"),
    ("agile", "", "backlog"),
    ("wiki", "", "wiki"),
    ("testmgmt", "plan", "plans"),
    ("testmgmt", "execution", "executions"),
    ("testmgmt", "run", "executions"),
    ("testmgmt", "coverage", "coverage"),
    ("testmgmt", "test_steps", "issues"),
    ("accounts", "user", "users"),
    ("core", "help", "help"),
]


def _nav_section(request):
    match = getattr(request, "resolver_match", None)
    if match is None:
        return ""
    for namespace, prefix, section in NAV_SECTIONS:
        if match.namespace == namespace and (match.url_name or "").startswith(prefix):
            return section
    return ""


def mpira_context(request):
    ctx = {"site_url": settings.SITE_URL, "nav_section": _nav_section(request)}
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from apps.projects.permissions import visible_projects

        ctx["unread_notifications"] = user.notifications.filter(is_read=False).count()
        ctx["nav_projects"] = visible_projects(user).only("key", "name")
    return ctx
