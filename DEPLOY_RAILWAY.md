# Deploying Mpira to Railway

Target setup: one Railway project with two services.

```
┌──────────────────────── Railway project "mpira" ─────────────────────────┐
│  web  (Dockerfile)                         Postgres (Railway plugin)     │
│   ├─ start: sh bin/release.sh          ───►  DATABASE_URL (private net)    │
│   │    migrate + ensure_admin (runs at start)                                            │
│   ├─ gunicorn on $PORT                                                   │
│   ├─ healthcheck: GET /healthz (checks DB)                               │
│   └─ Volume mounted at /data  → attachments in /data/media               │
└──────────────────────────────────────────────────────────────────────────┘
```

All deploy behaviour is in the repo:
- `Dockerfile` installs the app and collects static files at build time.
- `railway.json` selects the Dockerfile builder and sets the health check and the restart policy.
- `bin/release.sh` runs `migrate` and `ensure_admin` before gunicorn starts on every container start. Both steps are idempotent.

---

## Option A: Railway CLI

### 0. Prerequisites

```bash
npm i -g @railway/cli        # or: scoop install railway / brew install railway
railway login
```

Generate the secrets you'll need:

```bash
python -c "from django.core.management.utils import get_random_secret_key as g; print(g())"
```

### 1. Create the project and the database

Run these from the project folder (`ticket_mpira`):

```bash
railway init --name mpira
railway add --database postgres
```

### 2. Create the web service

**From GitHub** (recommended: every push to `main` auto-deploys):

```bash
git init && git add . && git commit -m "Initial Mpira"
gh repo create mpira --private --source . --push
railway add --repo <your-github-user>/mpira --service web
```

**Or from your local folder** (no GitHub needed):

```bash
railway add --service web
```

### 3. Set the environment variables

```bash
railway variables --service web \
  --set "DATABASE_URL=\${{Postgres.DATABASE_URL}}" \
  --set "SECRET_KEY=<paste the generated key>" \
  --set "MEDIA_ROOT=/data/media" \
  --set "MPIRA_ADMIN_EMAIL=you@yourcompany.com" \
  --set "MPIRA_ADMIN_PASSWORD=<a strong password>"
```

On PowerShell, put the reference in single quotes so `$` isn't expanded:
`--set 'DATABASE_URL=${{Postgres.DATABASE_URL}}'`.

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | ✓ | `${{Postgres.DATABASE_URL}}` (a reference to the Postgres service) |
| `SECRET_KEY` | ✓ | Long and random. `prod.py` refuses to boot without it. |
| `MEDIA_ROOT` | ✓ | `/data/media` (inside the Volume) |
| `MPIRA_ADMIN_EMAIL` / `MPIRA_ADMIN_PASSWORD` | first deploy | Creates the first Admin if missing. It never overwrites an existing user, so it's safe to leave set. |
| `ALLOWED_HOSTS` / `CSRF_TRUSTED_ORIGINS` | custom domain only | `RAILWAY_PUBLIC_DOMAIN` is trusted automatically |
| `SITE_URL` | optional | `https://your-domain` |
| `MAX_ACTIVE_USERS` | optional | default `15` |
| `MAX_ATTACHMENT_SIZE_MB` | optional | default `10` |
| `WEB_CONCURRENCY` | optional | gunicorn workers, default `3` |

`DJANGO_SETTINGS_MODULE` does not need setting: the Dockerfile defaults it to
`config.settings.prod`.

### 4. Attach a Volume for attachments

```bash
railway service web
railway volume add --mount-path /data
```

### 5. Deploy

If you connected GitHub, the first deploy starts by itself. Otherwise:

```bash
railway up --service web
```

Then give the service a public URL:

```bash
railway domain --service web
```

### 6. Verify

```bash
railway logs --service web
curl https://<your-app>.up.railway.app/healthz      # {"status": "ok", "database": "ok"}
```

Log in with `MPIRA_ADMIN_EMAIL`. Then go to **Users → Add user** to create the team,
and **New project** to start.

**Optional: demo data in production.** It creates the 4 demo users and the
`MPR` project. A password is mandatory outside DEBUG:

```bash
railway ssh --service web
python manage.py seed_demo --password '<demo password>'
```

`railway run …` executes on *your* machine. Railway's internal `DATABASE_URL`
host isn't reachable from there, so use `railway ssh` for one-off management
commands.

---

## Option B: Railway dashboard

1. **New Project** → **Deploy from GitHub repo**, and pick the repo. Railway detects `railway.json` and builds with the Dockerfile.
2. In the project canvas, add **+ Create** → **Database** → **PostgreSQL**.
3. Open the **web** service → **Variables** and add the variables from the table above. For `DATABASE_URL`, use **Add Reference** → Postgres → `DATABASE_URL`.
4. Open the **web** service → **Settings** → **Volumes** → **Add Volume**, with mount path `/data`.
5. Open **Settings** → **Networking** → **Generate Domain**.
6. **Settings** → **Deploy** should already show these values from `railway.json`:
   - No pre-deploy command needed: the container start runs `bin/release.sh`
   - Healthcheck path `/healthz`
7. Click **Deploy** if a deploy hasn't started. Then check **Deployments** → **View logs**.

---

## Custom domain (optional)

```bash
railway domain mpira.yourcompany.com --service web
```

The command prints the DNS record to create at your registrar (a CNAME and,
for some setups, a TXT verification record). Once it resolves, Railway issues
the TLS certificate automatically.

Then set the variables, comma-separating them if you keep several domains:

```bash
railway variables --service web \
  --set "ALLOWED_HOSTS=mpira.yourcompany.com" \
  --set "CSRF_TRUSTED_ORIGINS=https://mpira.yourcompany.com" \
  --set "SITE_URL=https://mpira.yourcompany.com"
```

The `*.up.railway.app` domain keeps working.

---

## Operations

**Deploys**
- With GitHub connected, a deploy is just a push to `main`.
- Migrations run at container start, before gunicorn serves traffic. A failing migration stops the new container and Railway keeps the previous one serving.
- With a Volume attached, Railway stops the old container before starting the new one, so expect a few seconds of downtime. This is the trade-off for local file storage.

**Backups**
- Enable them in the Postgres service: **Backups** tab.
- For attachments, snapshot the Volume (**Volume** → **Backups**), or move to S3/R2 later.

**Scaling**
- Raise `WEB_CONCURRENCY` before adding replicas.
- Multiple replicas need S3/R2 storage instead of a Volume.

**Rollback:** in **Deployments**, choose **Redeploy** on the previous successful deployment.

**Troubleshooting**

| Symptom | Fix |
|---|---|
| Crash on start | Check `railway logs`. It's usually `DATABASE_URL` missing or not referencing the Postgres service, or `SECRET_KEY` unset. |
| Health check fails | `SECRET_KEY` is missing (`prod.py` raises at startup), or the DB is unreachable. |
| `400 Bad Request` | The domain isn't in `ALLOWED_HOSTS`, which happens with a custom domain. |
| `403 CSRF` on login | Add `https://your-domain` to `CSRF_TRUSTED_ORIGINS`. |
| Attachments disappear after deploy | The Volume isn't mounted at `/data`, or `MEDIA_ROOT` isn't `/data/media`. |
