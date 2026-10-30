"""Adds a QA status and a QA board column to every project that does not have them yet.

    python manage.py add_qa_status            # apply
    python manage.py add_qa_status --dry-run  # only print what would change

The status goes into the workflow with the default moves (reachable from and to every other status, refined later
on the Workflow page). The column is placed right before the first column that holds a done status. Running the
command again changes nothing.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.agile import board
from apps.issues import workflow
from apps.projects.models import Project

NAME = "QA"


class Command(BaseCommand):
    help = "Add the QA status and QA board column to every project (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="print the changes without making them")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        for project in Project.objects.order_by("key"):
            with transaction.atomic():
                changes = self.sync(project, dry)
                if dry:  # the board may create its default columns on first read: undo that too
                    transaction.set_rollback(True)
            self.stdout.write(f"{project.key}: {', '.join(changes) if changes else 'already has QA, nothing to do'}")
        self.stdout.write(self.style.SUCCESS(f"Done ({'dry run, nothing saved' if dry else 'saved'})."))

    def sync(self, project, dry):
        changes = []
        status = next((s for s in workflow.statuses(project) if s.name.lower() == NAME.lower()), None)
        if status is None:
            changes.append(f"status {NAME} added")
            if not dry:
                status = workflow.add_status(project, NAME, counts_as_done=False)

        columns = board.ensure_columns(project)
        column = next((c for c in columns if c.name.lower() == NAME.lower()), None)
        if column is None:
            changes.append(f"column {NAME} added")
            if not dry:
                column = board.add_column(project, NAME)
                columns = board.ensure_columns(project)
                column = next(c for c in columns if c.pk == column.pk)  # fresh copy: the status may already sit here

        if dry:
            return changes

        if status.key not in column.statuses:
            changes.append(f"status {NAME} placed in column {NAME}")
            board.place_status(project, status.key, column.pk)
            columns = board.ensure_columns(project)
            column = next(c for c in columns if c.pk == column.pk)

        done = workflow.done_keys(project)
        done_index = next((i for i, c in enumerate(columns) if set(c.statuses) & done), len(columns) - 1)
        position = next(i for i, c in enumerate(columns) if c.pk == column.pk)
        if position > done_index:
            changes.append(f"column {NAME} moved before the done column")
            for _step in range(position - done_index):
                board.move_column(column, "up")
        return changes
