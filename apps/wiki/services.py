import difflib
import re

from django.db import connection, transaction
from django.db.models import Q

from apps.core.models import Notification
from apps.core.notifications import mentioned_users, notify
from apps.issues.models import Issue
from apps.projects.permissions import can

from .models import Page, PageVersion

ISSUE_REF_RE = re.compile(r"\[\[([A-Z][A-Z0-9]{1,9})-(\d+)\]\]")


def referenced_issues(text):
    refs = {(k, int(n)) for k, n in ISSUE_REF_RE.findall(text or "")}
    if not refs:
        return Issue.objects.none()
    q = Q()
    for key, number in refs:
        q |= Q(project__key=key, number=number)
    return Issue.objects.filter(q)


@transaction.atomic
def save_page(page, user, *, title, body, parent=None, change_note=""):
    """Create or update a page; every save produces a new immutable version."""
    is_new = page.pk is None
    old_body = "" if is_new else page.body
    if not is_new and page.title == title and page.body == body and page.parent_id == getattr(parent, "pk", None):
        return page, False
    page.title = title
    page.body = body
    page.parent = parent
    page.updated_by = user
    if is_new:
        page.created_by = user
        page.version = 1
    else:
        page.version += 1
    page.save()
    PageVersion.objects.create(
        page=page, version=page.version, title=title, body=body, change_note=change_note, author=user
    )
    page.linked_issues.set(referenced_issues(body))
    project = page.space.project
    mentioned = [u for u in mentioned_users(body, old_body) if can(u, project, "view")]
    notify(mentioned, user, Notification.Kind.PAGE_MENTION, page.title, page.get_absolute_url())
    return page, True


def restore_version(page, version, user):
    return save_page(
        page,
        user,
        title=version.title,
        body=version.body,
        parent=page.parent,
        change_note=f"Restored v{version.version}",
    )


def diff_lines(old, new):
    """[(kind, text)] where kind is '+', '-', ' ' or '@' for unified-diff rendering."""
    out = []
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=2):
        if line.startswith(("---", "+++")):
            continue
        out.append((line[:1] if line[:1] in "+-@" else " ", line))
    return out


def search_pages(spaces_qs, query):
    """Postgres full-text search with ranking; a plain icontains on SQLite."""
    pages = Page.objects.filter(space__in=spaces_qs).select_related("space__project")
    query = (query or "").strip()
    if not query:
        return pages.none()
    if connection.vendor == "postgresql":
        from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector

        vector = SearchVector("title", weight="A", config="simple") + SearchVector("body", weight="B", config="simple")
        sq = SearchQuery(query, config="simple", search_type="websearch")
        return (
            pages.annotate(rank=SearchRank(vector, sq))
            .filter(Q(rank__gt=0) | Q(title__icontains=query))
            .order_by("-rank", "title")
        )
    return pages.filter(Q(title__icontains=query) | Q(body__icontains=query)).order_by("title")


def page_tree(space):
    """Nested [(page, children)] for the sidebar, built from one query."""
    pages = list(space.pages.all().only("id", "title", "parent_id", "position"))
    by_parent = {}
    for p in pages:
        by_parent.setdefault(p.parent_id, []).append(p)

    def build(parent_id):
        return [(p, build(p.pk)) for p in by_parent.get(parent_id, [])]

    return build(None)
