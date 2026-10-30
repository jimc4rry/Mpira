import re

from django.contrib.auth import get_user_model

from .models import Notification

# @handle, but not the middle of an email address or a URL path.
MENTION_RE = re.compile(r"(?<![\w@/.])@([A-Za-z0-9_][A-Za-z0-9_.+-]*[A-Za-z0-9_]|[A-Za-z0-9_])")


def mentioned_handles(text):
    return {m.group(1).lower() for m in MENTION_RE.finditer(text or "")}


def mentioned_users(text, old_text=""):
    """Active users @mentioned in `text` but not already in `old_text`."""
    handles = mentioned_handles(text) - mentioned_handles(old_text)
    if not handles:
        return []
    User = get_user_model()
    return list(User.objects.filter(is_active=True, username__iregex=r"^(%s)$" % "|".join(map(re.escape, handles))))


def notify(recipients, actor, kind, target_label, target_url):
    seen = set()
    rows = []
    for user in recipients:
        if user is None or user.pk in seen or (actor and user.pk == actor.pk) or not user.is_active:
            continue
        seen.add(user.pk)
        rows.append(
            Notification(
                recipient=user,
                actor=actor,
                kind=kind,
                target_label=target_label[:300],
                target_url=target_url,
            )
        )
    Notification.objects.bulk_create(rows)
    return rows
