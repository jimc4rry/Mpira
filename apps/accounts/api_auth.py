"""
Bearer-token authentication for the REST API.

    Authorization: Bearer mpk_...      (or the X-API-Key header)

Keys are looked up by their hash. A revoked, expired or inactive-owner key is
rejected with 401. Read-only keys are refused on any write method (403).
"""

from django.utils import timezone
from rest_framework import authentication, exceptions, permissions

from .models import ApiKey

SAFE_METHODS = permissions.SAFE_METHODS
LAST_USED_RESOLUTION = 60  # seconds - avoid a write on every request


class ApiKeyAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        raw = request.headers.get("X-API-Key", "")
        if not raw:
            header = request.headers.get("Authorization", "")
            if header.startswith("Bearer "):
                raw = header[7:].strip()
        if not raw:
            return None  # let other authenticators try (session, basic)
        if not raw.startswith(ApiKey.PREFIX):
            raise exceptions.AuthenticationFailed("Invalid API key.")
        key = ApiKey.objects.select_related("user").filter(key_hash=ApiKey.hash_key(raw)).first()
        if key is None or not key.is_active:
            raise exceptions.AuthenticationFailed("Invalid or expired API key.")
        if not key.user.is_active:
            raise exceptions.AuthenticationFailed("Invalid API key.")
        now = timezone.now()
        if key.last_used_at is None or (now - key.last_used_at).total_seconds() > LAST_USED_RESOLUTION:
            ApiKey.objects.filter(pk=key.pk).update(last_used_at=now)
        return key.user, key

    def authenticate_header(self, request):
        return 'Bearer realm="mpira"'


class ReadOnlyKeyPermission(permissions.BasePermission):
    """Write requests with a read-only API key are forbidden."""

    message = "This API key is read-only."

    def has_permission(self, request, view):
        auth = request.auth
        if isinstance(auth, ApiKey) and auth.read_only and request.method not in SAFE_METHODS:
            return False
        return True
