"""Adds the Canceled status to every project that does not have it yet.

    python manage.py add_canceled_status            # apply
    python manage.py add_canceled_status --dry-run  # only print what would change

Canceled is for work that is dropped (a duplicate, or not needed). It counts as done: it leaves the open lists and the
sprints, and it can be reached from and move to every other status. On the board it sits in the last column with the
other done work. Running the command again changes nothing.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.agile import board
from apps.issues import workflow
from apps.projects.models import Project


class Command(BaseCommand):
    help = "Add the Canceled status to every project (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="print the changes without making them")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        for project in Project.objects.order_by("key"):
            with transaction.atomic():
                changes = self.sync(project)
                if dry:  # creating the default statuses or columns is a write too: undo everything in a dry run
                    transaction.set_rollback(True)
            self.stdout.write(f"{project.key}: {', '.join(changes) if changes else 'already has Canceled, nothing to do'}")
        self.stdout.write(self.style.SUCCESS(f"Done ({'dry run, nothing saved' if dry else 'saved'})."))

    def sync(self, project):
        changes = []
        if not any(s.key == workflow.CANCELED_KEY for s in workflow.statuses(project)):
            changes.append("status Canceled added")
        workflow.add_canceled(project)
        board.ensure_columns(project)  # places the status on the board, in the last column
        return changes
