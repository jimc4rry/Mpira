"""Outgoing webhooks: a signed JSON POST to each active hook of the project that listens for the event.

The request is sent after the database change is committed (`transaction.on_commit`), so a rolled-back change is never
announced. Each send has a 5-second timeout, and its outcome (HTTP status or error) is kept on the hook. A failing hook
never fails the user's action.

Signature: header `X-Mpira-Signature: sha256=<hex>` is the HMAC-SHA256 of the exact request body with the hook's secret.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import urllib.error
import urllib.request
from urllib.parse import urlparse

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)
TIMEOUT_SECONDS = 5
BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}


def address_problem(url):
    """Why an address may not be used as a webhook target, or None. https only, and no literal private addresses."""
    parts = urlparse(url)
    if parts.scheme != "https":
        return "Η διεύθυνση πρέπει να ξεκινά με https://."
    host = (parts.hostname or "").lower()
    if not host or host in BLOCKED_HOSTS or host.endswith(".localhost"):
        return "Η διεύθυνση δεν μπορεί να δείχνει σε τοπικό μηχάνημα."
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None  # a name: resolved when sent (see the limits in docs/MPIRA.md)
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        return "Η διεύθυνση δεν μπορεί να είναι ιδιωτική ή τοπική."
    return None


def sign(secret, body):
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def send(hook, event, payload):
    """One POST to one hook. Records the outcome on the hook; returns True when the receiver answered 2xx."""
    body = json.dumps({"event": event, "sent_at": timezone.now().isoformat(), **payload},
                      ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        hook.url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Mpira-Webhook/1",
            "X-Mpira-Event": event,
            "X-Mpira-Signature": sign(hook.secret, body),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status, error = response.status, ""
    except urllib.error.HTTPError as exc:
        status, error = exc.code, f"HTTP {exc.code}"
    except Exception as exc:  # network, DNS, timeout: the action itself must still succeed
        status, error = None, type(exc).__name__
    hook.last_status, hook.last_error = status, error[:200]
    hook.save(update_fields=["last_status", "last_error"])
    if error:
        logger.warning("webhook %s failed for %s: %s", hook.pk, event, error)
    return status is not None and 200 <= status < 300


def emit(project, event, payload):
    """Queues the event for every active hook of the project that listens for it."""
    hooks = [h for h in project.webhooks.filter(active=True) if event in h.event_list]
    if not hooks:
        return
    pk_list = [h.pk for h in hooks]

    def deliver():
        from .models import Webhook  # the list is reloaded so each send saves its own outcome

        for hook in Webhook.objects.filter(pk__in=pk_list, active=True):
            send(hook, event, payload)

    transaction.on_commit(deliver)


def issue_payload(issue):
    return {
        "project": issue.project.key,
        "issue": {
            "key": issue.key,
            "title": issue.title,
            "type": issue.issue_type,
            "status": issue.status,
            "priority": issue.priority,
            "url": issue.get_absolute_url(),
        },
    }
