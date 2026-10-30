# Mpira

A self-hosted, Jira-inspired project tool for small teams (up to ~15 people):
**issues & agile boards**, a **Confluence-style wiki** and **Xray-style test
management** in one Django app, bilingual **English / Ελληνικά**, deployable to
Railway with one Postgres database.

| | |
|---|---|
| **Issues** | Epics, Stories, Tasks, Bugs, Sub-tasks, Tests · keys like `MPR-42` · priorities, labels, components, fix versions, due dates · per-project custom fields (text / number / date / select / checkbox, optionally per issue type) · comments with Markdown and `@mentions` · attachments · watchers · issue links (blocks / relates / duplicates / tests) · full activity history |
| **Workflow** | To Do → In Progress → In Review → Done (with reopen). Enforced everywhere: forms, API, and board drag & drop. |
| **Agile** | Kanban board with drag & drop (only legal workflow moves accept a drop) · Scrum backlog with drag & drop sprint planning and ranking · create / start / complete sprints (incomplete work moves to the backlog or the next sprint) · story points · **burndown** (with ideal guideline) · **velocity** chart · sprint report |
| **Wiki** | One space per project · hierarchical pages · Markdown with live preview · every save is a version (history, diff, restore) · optimistic-locking against overwriting a teammate's newer save · `[[MPR-12]]` embeds a live issue chip, and the issue lists the pages that mention it · full-text search (Postgres) |
| **Tests** | Test cases as an issue type with manual steps · Test Plans · Test Executions with Pass / Fail / Blocked / To Do per test, recorded inline · traceability via “tests” links · **coverage report** per requirement (Uncovered / Not run / OK / Failing / Blocked), filterable by version |
| **Users** | Email + password login · workspace roles Admin / Project Manager / Developer / Tester / Viewer · **per-project roles** · in-app notifications (mentions, assignments, comments, status changes) · 15 active-seat limit (configurable) |
| **API** | REST (`/api/v1/`), session or Basic auth, validated input, uniform JSON errors |

---

## Quick start (Windows)

Double-click **`run.bat`** (or run it from a terminal). It will:

1. create `.venv` and install the requirements (only when they change),
2. create `.env` from `.env.example`,
3. migrate the SQLite database and load demo data,
4. open http://127.0.0.1:8000.

Demo logins (password = `DEMO_PASSWORD` in `.env`, `mpira-demo-2026` by default):

| Email | Role |
|---|---|
| `admin@mpira.local` | Admin (also Django superuser) |
| `maria@mpira.local` | Project Manager |
| `nikos@mpira.local` | Developer |
| `eleni@mpira.local` | Tester |

`run.bat lan` makes it reachable from other PCs on your network; `run.bat reset`
wipes the local database and re-seeds. **`test.bat`** runs the same checks as CI.

### Manual setup (any OS)

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py seed_demo           # optional demo data
python manage.py runserver
```

Without `DATABASE_URL` the app uses SQLite. To develop against Postgres:
`docker compose up -d db` and set `DATABASE_URL=postgres://mpira:mpira@localhost:5432/mpira`
in `.env`. `docker compose up --build` runs the real production image locally.

### Tests

```bash
python manage.py test          # 72 tests: auth, permissions, issue CRUD, workflow,
                               # sprint lifecycle + burndown, wiki, test mgmt, API
```

`manage.py test` automatically uses `config/settings/test.py`.

---

## Architecture

```
config/
  settings/base.py    everything shared; all config from env (django-environ)
  settings/dev.py     DEBUG, sqlite fallback, open ALLOWED_HOSTS
  settings/test.py    fast hashing, quiet logs
  settings/prod.py    HSTS/secure cookies, Railway domain auto-trust, startup guards
  urls.py
apps/
  accounts/   custom User (email login, @handle, workspace role, language), user admin UI
  core/       dashboard, notifications, global search, /healthz, Markdown renderer,
              template tags, seed_demo + ensure_admin commands, shared test factories
  projects/   Project, ProjectMembership (per-project role), Component, Version, Label,
              permissions.py  ← the single permission matrix used by every view & the API
  issues/     Issue, Comment, Attachment, IssueLink, Activity, CustomFieldDefinition,
              services.py     ← every issue write (activity log, workflow, notifications)
              custom_fields.py← one validator shared by HTML forms and the API
  agile/      Sprint, board / backlog / reports views,
              services.py     ← sprint lifecycle, burndown, velocity, SVG chart geometry
  wiki/       Space (1 per project), Page (tree), PageVersion, search, diff
  testmgmt/   TestStep, TestPlan, TestExecution, TestRun, coverage report
  api/        DRF serializers/views, uniform error handler
templates/    base layout + shared partials        static/  one CSS file + 3 small JS files
locale/el/    Greek translations (.po + compiled .mo, committed)
```

**Request flow:** views and API endpoints are thin. They resolve the project
through `projects.permissions.get_project_or_404()` and then call a service
function (`issues.services`, `agile.services`, `wiki.services`,
`testmgmt.services`). The UI and the API share the same rules, activity log and
notifications.

**Permissions:** workspace Admins can do everything everywhere. Everyone else
needs a `ProjectMembership`, whose role maps to capabilities:

| Capability | PM | Developer | Tester | Viewer |
|---|:-:|:-:|:-:|:-:|
| view | ✓ | ✓ | ✓ | ✓ |
| create/edit/transition issues, comment, edit wiki | ✓ | ✓ | ✓ | |
| delete issues, manage sprints, project settings & members | ✓ | | | |
| manage test plans/executions/steps | ✓ | | ✓ | |
| record test results | ✓ | ✓ | ✓ | |

- **Non-members** get **404**, so a project's existence isn't revealed.
- **Members without a capability** get **403**.
- **Cross-project references** (issue links, `[[KEY-1]]` embeds) are only shown when the viewer can see the other project.

**Burndown:** the actual line is rebuilt from the issue activity log (status
transitions), so it needs no daily cron snapshots.
- Starting a sprint freezes the committed scope; this is the baseline of the ideal line.
- Completing a sprint freezes the final scope, so the chart stays correct after unfinished issues move on.

**Front-end:** server-rendered Django templates with vanilla JS, and no build step.
- Drag & drop calls the JSON API, which re-validates the move.
- Charts are inline SVG computed server-side.
- Light and dark themes follow the OS setting and can be toggled.

**Attachments** are stored under `MEDIA_ROOT` (a Railway Volume in production)
and are never served publicly. They are streamed by a view that checks project
permissions.

### REST API

All endpoints live under `/api/v1/`. Authentication is session (with CSRF) or
HTTP Basic (email + password). Lists are paginated, 50 per page.

| Method | Path | |
|---|---|---|
| GET | `me/` | current user |
| POST | `markdown-preview/` | `{text}` → sanitized HTML |
| GET | `projects/`, `projects/{KEY}/` | |
| GET, POST | `projects/{KEY}/issues/` | filters: `status`, `type`, `priority`, `assignee` (id or `none`), `sprint` (id or `backlog`), `q` |
| GET, PATCH, DELETE | `projects/{KEY}/issues/{n}/` | `status` is read-only; use `transition/` |
| POST | `projects/{KEY}/issues/{n}/transition/` | `{status}` (409 if the workflow forbids it) |
| POST | `projects/{KEY}/issues/{n}/move/` | `{status?, sprint?, before?, after?}` (board/backlog drag & drop) |
| GET, POST | `projects/{KEY}/issues/{n}/comments/` | |
| GET, POST | `projects/{KEY}/sprints/` | |
| GET, PATCH | `projects/{KEY}/sprints/{id}/` | |
| POST | `projects/{KEY}/sprints/{id}/start/`, `…/complete/` | `{start_date, end_date}` / `{move_to}` |
| GET | `projects/{KEY}/sprints/{id}/burndown/`, `projects/{KEY}/velocity/` | |
| GET, PATCH | `projects/{KEY}/test-runs/{id}/` | `{status: pass/fail/blocked/todo, comment}` |
| GET | `projects/{KEY}/coverage/` | |

Every error has the same shape:

```json
{"error": {"code": "validation_error", "message": "Invalid input.", "details": {"title": ["This field may not be blank."]}}}
```

The `code` field is one of: `validation_error` (400), `not_authenticated` (401),
`permission_denied` (403), `not_found` (404) or `conflict` (409, for a workflow
or sprint rule).

---

## Internationalization

Every string goes through `{% trans %}` or `gettext`. Greek lives in
`locale/el/LC_MESSAGES/django.po`, and the compiled `.mo` is committed.

Language selection:
- Logged-in users get their profile language; the EN/EL button in the header changes it.
- First-time visitors get English (the same convention as minitools).

After you add or change strings:

```bash
python manage.py makemessages -l el --ignore=.venv --no-location
# fill in the new msgstr entries, then CHECK for "#, fuzzy" - makemessages
# guesses translations for similar strings and is often wrong
python manage.py compilemessages -l el --ignore=.venv
```

---

## Deploying

See **[DEPLOY_RAILWAY.md](DEPLOY_RAILWAY.md)** for the step-by-step guide.

The setup in brief:
- **Services:** two Railway services, `web` (built from the Dockerfile) and **PostgreSQL**.
- **Storage:** a Volume mounted at `/data` holds the attachments.
- **Release step:** migrations run at container start (`bin/release.sh`), before gunicorn.
- **Health check:** `/healthz` checks the database.

## API keys & AI assistants

Every user can create personal API keys on **Profile → API keys**. A key acts as
its owner, with the same project access. It is shown once and stored only as a
hash; it can be revoked at any time, and read-only keys can't change anything.

```bash
curl -H "Authorization: Bearer mpk_…" https://your-host/api/v1/issues/?assignee=me&open=true
curl -X POST -H "Authorization: Bearer mpk_…" -H "Content-Type: application/json"      -d '{"title":"New bug","issue_type":"bug"}' https://your-host/api/v1/projects/MPR/issues/
```

To let Claude read and write tickets, use the Mpira MCP server in
[tools/mpira-mcp](tools/mpira-mcp/README.md). It works with Claude Desktop and Claude Code.

## Design decisions & what's intentionally left out

- **Django and server-rendered templates instead of an SPA.** This matches the
  conventions of the `minitools` project: Django 5.2, `django-environ`, the
  split settings, namespaced apps, the 404-for-non-members rule, vanilla JS and
  Railway. For 15 users it means fewer moving parts, no build pipeline, and one
  deployable unit. DRF is the one addition, for a validated REST API.
- **A fixed workflow** (four statuses, defined in code). There is no workflow
  designer. Per-project custom fields cover most configurability needs.
- **No realtime** (websockets). Pages refresh after each action, and drag & drop
  is optimistic with server validation.
- **Markdown, not WYSIWYG**, for the wiki. It is versionable, diffable and safe:
  output is sanitized with `nh3`.
- **No email notifications yet.** Notifications are in-app; SMTP settings exist
  for a future digest.
- **Xray features left out on purpose:** no Gherkin/Cucumber, no CI imports, no
  automated test results, no test sets or preconditions.
- **No OAuth or SSO in v1**, and **no self-signup**: an Admin creates the
  accounts, which fits a closed team workspace.
- **Attachments use a Railway Volume.** That means a single replica and a few
  seconds of downtime per deploy. Moving to S3/R2 later only needs
  `django-storages` and a `STORAGES["default"]` change.
