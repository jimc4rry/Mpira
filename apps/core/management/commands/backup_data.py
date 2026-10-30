"""Writes a JSON copy of the data to backups/ (or --dir).

    python manage.py backup_data
    python manage.py backup_data --dir /var/backups/mpira

The file holds the user accounts (password hashes) and project data, so it stays out of git and the Docker image
(both ignore backups/). Sessions are left out: they are live login tokens, not data worth keeping.
Restore on an empty database with `python manage.py loaddata <file>`.
"""

import datetime
import pathlib

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Write a JSON dump of the data to backups/ (or --dir)."

    def add_arguments(self, parser):
        parser.add_argument("--dir", default=str(settings.BASE_DIR / "backups"))

    def handle(self, *args, **options):
        target = pathlib.Path(options["dir"])
        target.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        path = target / f"mpira-{stamp}.json"
        with path.open("w", encoding="utf-8") as fh:
            call_command("dumpdata", "--exclude", "sessions", "--indent", "2", stdout=fh)
        self.stdout.write(self.style.SUCCESS(f"Wrote {path}"))
