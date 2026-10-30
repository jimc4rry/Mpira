"""
Idempotently create the first workspace admin from env vars, so a fresh
Railway deploy needs no interactive `createsuperuser`:

    MPIRA_ADMIN_EMAIL=you@company.com
    MPIRA_ADMIN_PASSWORD=<strong password>

Does nothing if the variables are unset or the user already exists (the
password of an existing user is never overwritten).
"""

import os

from django.core.management.base import BaseCommand

from apps.accounts.models import Role, User


class Command(BaseCommand):
    help = "Create the initial admin from MPIRA_ADMIN_EMAIL / MPIRA_ADMIN_PASSWORD if missing."

    def handle(self, *args, **options):
        email = (os.environ.get("MPIRA_ADMIN_EMAIL") or "").strip().lower()
        password = os.environ.get("MPIRA_ADMIN_PASSWORD") or ""
        if not email or not password:
            self.stdout.write("ensure_admin: MPIRA_ADMIN_EMAIL/PASSWORD not set - skipping.")
            return
        if User.objects.filter(email=email).exists():
            self.stdout.write(f"ensure_admin: {email} already exists - skipping.")
            return
        User.objects.create_superuser(username=email.split("@")[0], email=email, password=password, role=Role.ADMIN)
        self.stdout.write(self.style.SUCCESS(f"ensure_admin: created admin {email}."))
