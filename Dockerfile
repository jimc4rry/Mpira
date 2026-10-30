FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Static files are collected at build time with the production (hashed,
# compressed) storage. Dummy values only satisfy prod.py's startup guards;
# nothing here is used at runtime.
RUN SECRET_KEY=build-only-placeholder ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput

EXPOSE 8000

# bin/release.sh is idempotent: it applies pending migrations and creates the
# first admin from env vars only when missing. Running it on every start keeps
# deploys simple (Railway's preDeployCommand is not used - see DEPLOY_RAILWAY.md).
CMD ["sh", "-c", "sh bin/release.sh && exec gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers ${WEB_CONCURRENCY:-3} --timeout 60 --access-logfile -"]
