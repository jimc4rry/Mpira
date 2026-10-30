from .base import *  # noqa: F401,F403
from .base import ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, SECRET_KEY, env

DEBUG = False

# Railway injects the public domain of the service; trust it automatically
# so ALLOWED_HOSTS/CSRF don't need to be kept in sync by hand.
_railway_domain = env("RAILWAY_PUBLIC_DOMAIN", default=None)
if _railway_domain:
    ALLOWED_HOSTS.append(_railway_domain)
    CSRF_TRUSTED_ORIGINS.append(f"https://{_railway_domain}")

if not ALLOWED_HOSTS:
    raise RuntimeError(
        "ALLOWED_HOSTS is empty in production. Set the ALLOWED_HOSTS env var "
        "(comma-separated) or ensure RAILWAY_PUBLIC_DOMAIN is available."
    )

# Railway's healthcheck probes from this host - see railway.json.
ALLOWED_HOSTS.append("healthcheck.railway.app")

if SECRET_KEY.startswith("django-insecure"):
    raise RuntimeError(
        "SECRET_KEY is not set in production. Generate one with: python -c "
        "\"from django.core.management.utils import get_random_secret_key as g; print(g())\""
    )

SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
# /healthz is probed over plain HTTP inside Railway's network.
SECURE_REDIRECT_EXEMPT = [r"^healthz$"]
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
# HSTS preload is a one-way door for a custom domain - opt in deliberately.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
