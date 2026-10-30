from .base import *  # noqa: F401,F403

DEBUG = True
# Wide open on purpose: only ever used on your machine / LAN (run.bat).
ALLOWED_HOSTS = ["*"]

# Plain static storage in dev so runserver works without collectstatic.
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
}
