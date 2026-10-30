from django import template
from django.utils.html import format_html
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.core.markdown import render_markdown
from apps.issues.models import IssueType, Priority

register = template.Library()

TYPE_ICONS = {
    IssueType.EPIC: "⚡",
    IssueType.STORY: "📗",
    IssueType.TASK: "☑",
    IssueType.BUG: "🐞",
    IssueType.SUBTASK: "↳",
    IssueType.TEST: "🧪",
}
PRIORITY_ICONS = {
    Priority.HIGHEST: "⏫",
    Priority.HIGH: "🔼",
    Priority.MEDIUM: "⏺",
    Priority.LOW: "🔽",
    Priority.LOWEST: "⏬",
}
CHOICE_FIELDS = {"issue_type": IssueType, "priority": Priority}
FIELD_LABELS = {
    "title": gettext_lazy("Summary"),
    "description": gettext_lazy("Description"),
    "issue_type": gettext_lazy("Type"),
    "priority": gettext_lazy("Priority"),
    "assignee": gettext_lazy("Assignee"),
    "epic": gettext_lazy("Epic"),
    "parent": gettext_lazy("Parent"),
    "sprint": gettext_lazy("Sprint"),
    "story_points": gettext_lazy("Story points"),
    "due_date": gettext_lazy("Due date"),
    "labels": gettext_lazy("Labels"),
    "components": gettext_lazy("Components"),
    "fix_versions": gettext_lazy("Fix versions"),
    "status": gettext_lazy("Status"),
}


@register.simple_tag(takes_context=True)
def markdown(context, text):
    request = context.get("request")
    return render_markdown(text, getattr(request, "user", None))


@register.filter
def type_icon(issue_type):
    return TYPE_ICONS.get(issue_type, "•")


@register.filter
def priority_icon(priority):
    return PRIORITY_ICONS.get(priority, "")


@register.simple_tag
def type_badge(issue):
    return format_html(
        '<span class="type-badge type-{}" title="{}">{}</span>',
        issue.issue_type,
        issue.get_issue_type_display(),
        TYPE_ICONS.get(issue.issue_type, "•"),
    )


@register.simple_tag
def status_pill(status, label=None):
    if label is None:
        label = status
    return format_html('<span class="pill status-{}">{}</span>', status, label)


@register.simple_tag
def avatar(user, size="sm"):
    if user is None:
        return format_html('<span class="avatar avatar-{} is-empty" title="{}">?</span>', size, _("Unassigned"))
    hue = (user.pk * 47) % 360
    return format_html(
        '<span class="avatar avatar-{}" style="--hue:{}" title="{}">{}</span>',
        size,
        hue,
        user.display_name,
        user.initials,
    )


@register.filter
def field_label(field):
    if field.startswith("cf:"):
        return field[3:]
    label = FIELD_LABELS.get(field)
    return str(label) if label else field


@register.filter
def activity_value(value, field):
    enum = CHOICE_FIELDS.get(field)
    if enum and value:
        try:
            return enum(value).label
        except ValueError:
            return value
    return value or "—"


@register.filter
def get_item(mapping, key):
    if mapping is None:
        return None
    return mapping.get(key)


@register.simple_tag(takes_context=True)
def query_replace(context, **kwargs):
    params = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v in (None, ""):
            params.pop(k, None)
        else:
            params[k] = v
    return params.urlencode()


@register.filter
def filesize(num):
    num = num or 0
    for unit in ("B", "KB", "MB"):
        if num < 1024:
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"
