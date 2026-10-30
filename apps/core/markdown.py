"""
Markdown → sanitized HTML, plus Mpira extensions applied *after* sanitizing:
- [[KEY-123]] becomes a live issue chip (only for issues the viewer can see)
- @handle becomes a highlighted mention
"""

import re

import markdown as md
import nh3
from django.utils.html import escape
from django.utils.safestring import mark_safe

from .notifications import MENTION_RE

ALLOWED_TAGS = {
    "p", "br", "hr", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "em", "del", "code", "pre",
    "blockquote", "ul", "ol", "li", "a", "table", "thead", "tbody", "tr", "th", "td", "img", "span",
}
ALLOWED_ATTRIBUTES = {"a": {"href", "title"}, "img": {"src", "alt", "title"}, "th": {"align"}, "td": {"align"}}
ISSUE_REF_RE = re.compile(r"\[\[([A-Z][A-Z0-9]{1,9})-(\d+)\]\]")
# Only touch text outside of tags / code blocks.
CODE_SPLIT_RE = re.compile(r"(<pre>.*?</pre>|<code>.*?</code>|<[^>]+>)", re.S)


def _issue_lookup(text, user):
    from apps.issues.models import Issue
    from apps.projects.permissions import can

    refs = {(k, int(n)) for k, n in ISSUE_REF_RE.findall(text)}
    if not refs:
        return {}
    from django.db.models import Q

    q = Q()
    for key, number in refs:
        q |= Q(project__key=key, number=number)
    found = {}
    for issue in Issue.objects.filter(q).select_related("project"):
        if user is not None and can(user, issue.project, "view"):
            found[issue.key] = issue
    return found


def _chip(issue):
    return (
        f'<a class="issue-chip status-{issue.status}{" is-done" if issue.is_done else ""}" '
        f'href="{issue.get_absolute_url()}" title="{escape(issue.get_status_display())}">'
        f'<span class="issue-chip-type type-{issue.issue_type}"></span>'
        f"<strong>{escape(issue.key)}</strong> {escape(issue.title)}"
        f'<span class="issue-chip-status">{escape(issue.get_status_display())}</span></a>'
    )


def render_markdown(text, user=None):
    if not text:
        return mark_safe("")
    html = md.markdown(text, extensions=["fenced_code", "tables", "sane_lists", "nl2br"])
    html = nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer",
    )
    issues = _issue_lookup(html, user)

    def enrich(segment):
        def issue_sub(m):
            key = f"{m.group(1)}-{m.group(2)}"
            return _chip(issues[key]) if key in issues else f'<span class="issue-chip is-missing">{escape(key)}</span>'

        segment = ISSUE_REF_RE.sub(issue_sub, segment)
        return MENTION_RE.sub(lambda m: f'<span class="mention">@{m.group(1)}</span>', segment)

    parts = CODE_SPLIT_RE.split(html)
    out = []
    for part in parts:
        if not part or part.startswith("<"):
            out.append(part)
        else:
            out.append(enrich(part))
    return mark_safe("".join(out))
