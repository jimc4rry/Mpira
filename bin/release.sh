#!/bin/sh
# Runs before gunicorn on every container start (see Dockerfile CMD).
# Both steps are idempotent: migrations only apply pending ones, and
# ensure_admin never overwrites an existing user.
set -e
python manage.py migrate --noinput
python manage.py ensure_admin
