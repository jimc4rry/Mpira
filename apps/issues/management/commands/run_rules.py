"""Runs the daily automation rules once.

    python manage.py run_rules

Put it on a schedule once a day (a Railway cron service, or any scheduler that can run a command). Each enabled rule
with the trigger "every day" runs for the issues its condition matches, as the user who created the rule. Running it
twice in a day is harmless: a daily rule only repeats actions that leave the issue as it already is.
"""

from django.core.management.base import BaseCommand

from apps.issues.automation import run_scheduled
from apps.issues.models import Rule


class Command(BaseCommand):
    help = "Run the enabled daily automation rules once."

    def handle(self, *args, **options):
        rules = Rule.objects.filter(enabled=True, trigger=Rule.Trigger.SCHEDULED).select_related("project", "created_by")
        total = 0
        for rule in rules:
            try:
                changed = run_scheduled(rule)
            except Exception as exc:  # one rule that cannot run must not stop the others
                self.stderr.write(f"{rule.project.key} · {rule.name}: {type(exc).__name__}: {exc}")
                continue
            total += changed
            self.stdout.write(f"{rule.project.key} · {rule.name}: {changed} issues")
        self.stdout.write(self.style.SUCCESS(f"{rules.count()} rules run, {total} changes."))
