"""
Bulk issue import from CSV, Excel (.xlsx) or JSON.

All three formats are read into the same shape - a header list and rows of
strings - and then go through one validator. Every row is checked first and
the whole file is rejected with per-row errors if anything is wrong. Only a
fully valid file is written, in a single transaction, so a half-imported
backlog is never left behind.
"""

import csv
import datetime
import io
import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from apps.agile.models import Sprint

from . import services
from .custom_fields import clean_custom_fields
from .models import IssueType, Priority

MAX_ROWS = 500
MAX_BYTES = 1024 * 1024

COLUMNS = [
    "issue_type",
    "title",
    "description",
    "priority",
    "assignee",
    "epic",
    "parent",
    "sprint",
    "story_points",
    "due_date",
    "labels",
    "components",
    "fix_versions",
]
REQUIRED = {"issue_type", "title"}

# Shown in the Help sheet of the Excel template and on the import page.
COLUMN_NOTES = {
    "issue_type": gettext_lazy("epic, story, task, bug, subtask or test. Required."),
    "title": gettext_lazy("Summary, up to 255 characters. Required."),
    "description": gettext_lazy("Markdown is supported."),
    "priority": gettext_lazy("highest, high, medium, low or lowest. Default medium."),
    "assignee": gettext_lazy("Email or handle of a project member."),
    "epic": gettext_lazy("Key of an epic in this project, e.g. MPR-1."),
    "parent": gettext_lazy("Key of the parent issue. Required for sub-tasks."),
    "sprint": gettext_lazy("Name of an open sprint."),
    "story_points": gettext_lazy("Whole number from 0 to 1000."),
    "due_date": gettext_lazy("YYYY-MM-DD."),
    "labels": gettext_lazy("Names separated by semicolons (;)."),
    "components": gettext_lazy("Names separated by semicolons (;)."),
    "fix_versions": gettext_lazy("Names separated by semicolons (;)."),
    "cf_<key>": gettext_lazy("A custom field of this project, e.g. cf_environment."),
}

EXAMPLE_ROWS = [
    {"issue_type": "epic", "title": "Checkout redesign", "description": "One-page checkout", "priority": "high"},
    {
        "issue_type": "story",
        "title": "Pay with saved card",
        "description": "Use PSP tokens, never PANs",
        "priority": "medium",
        "assignee": "nikos@mpira.local",
        "epic": "MPR-1",
        "sprint": "MPR Sprint 3",
        "story_points": "5",
        "due_date": "2026-11-30",
        "labels": "ux;security",
        "components": "Payments",
        "fix_versions": "1.1",
    },
    {"issue_type": "task", "title": "Feature flag for new checkout", "priority": "low", "story_points": "1", "labels": "tech-debt"},
    {
        "issue_type": "bug",
        "title": "Coupon accepts expired codes",
        "description": "Steps: apply SUMMER23 after 1 Sept",
        "priority": "highest",
        "story_points": "2",
        "labels": "security",
        "components": "Backend",
        "fix_versions": "1.1",
        "cf_impact": "High",
    },
    {"issue_type": "subtask", "title": "Mobile layout", "priority": "medium", "parent": "MPR-2"},
]

FORMATS = {
    "csv": {"label": "CSV", "mime": "text/csv; charset=utf-8", "ext": "csv"},
    "xlsx": {
        "label": "Excel (.xlsx)",
        "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "ext": "xlsx",
    },
    "json": {"label": "JSON", "mime": "application/json; charset=utf-8", "ext": "json"},
}


class ImportFormatError(Exception):
    pass


# --------------------------------------------------------------------- templates
def _example_dicts():
    # Every row gets every column so the header is complete in each format.
    return [{k: r.get(k, "") for k in COLUMNS} for r in EXAMPLE_ROWS]


def template_csv_text():
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(COLUMNS)
    for row in _example_dicts():
        writer.writerow([row[k] for k in COLUMNS])
    return buf.getvalue()


def template_json_text():
    # Same columns as the CSV/Excel templates (no custom fields - those depend on the project).
    payload = {"issues": [{k: v for k, v in row.items() if k in COLUMNS and v != ""} for row in EXAMPLE_ROWS]}
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def template_xlsx_bytes():
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Issues"
    ws.append(COLUMNS)
    header_font = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="2F6BFF")
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = fill
        cell.alignment = Alignment(vertical="center")
    for row in _example_dicts():
        values = [int(row[k]) if k == "story_points" and row[k] else row[k] for k in COLUMNS]
        ws.append(values)
    for idx, col in enumerate(COLUMNS, start=1):
        ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = 22 if col != "description" else 36
    ws.freeze_panes = "A2"

    help_ws = wb.create_sheet("Help")
    help_ws.append([_("Column"), _("Notes")])
    for cell in help_ws[1]:
        cell.font = header_font
        cell.fill = fill
    for col in COLUMNS:
        help_ws.append([col, str(COLUMN_NOTES[col])])
    help_ws.append(["cf_<key>", str(COLUMN_NOTES["cf_<key>"])])
    help_ws.append([])
    help_ws.append([_("Delete the example rows on the Issues sheet before uploading.")])
    help_ws.column_dimensions["A"].width = 18
    help_ws.column_dimensions["B"].width = 80

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def template_bytes(fmt):
    if fmt == "csv":
        return template_csv_text().encode("utf-8-sig")
    if fmt == "json":
        return template_json_text().encode("utf-8")
    if fmt == "xlsx":
        return template_xlsx_bytes()
    raise ValueError(fmt)


# ----------------------------------------------------------------------- readers
def _text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, list):
        return ";".join(_text(v) for v in value)
    return str(value).strip()


def _read_csv(raw):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportFormatError(_("The file must be UTF-8 encoded (save it as “CSV UTF-8” in Excel)."))
    reader = csv.reader(io.StringIO(text))
    try:
        headers = next(reader)
    except StopIteration:
        raise ImportFormatError(_("The file is empty."))
    return headers, [dict(zip(headers, row)) for row in reader]


def _read_xlsx(raw):
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 - any parse failure means "not a valid workbook"
        raise ImportFormatError(_("This Excel file could not be read. Save it as .xlsx and try again."))
    ws = wb[wb.sheetnames[0]]
    rows_iter = ws.iter_rows(values_only=True)
    try:
        headers = [_text(h) for h in next(rows_iter)]
    except StopIteration:
        raise ImportFormatError(_("The file is empty."))
    rows = [dict(zip(headers, (_text(v) for v in row))) for row in rows_iter]
    wb.close()
    return headers, rows


def _read_json(raw):
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ImportFormatError(_("The JSON file is not valid JSON."))
    if isinstance(payload, dict):
        payload = payload.get("issues")
    if not isinstance(payload, list):
        raise ImportFormatError(_("JSON must be a list of issues, or an object with an \"issues\" list."))
    headers = list(COLUMNS)
    rows = []
    for item in payload:
        if not isinstance(item, dict):
            raise ImportFormatError(_("Every JSON issue must be an object."))
        flat = {}
        for key, value in item.items():
            key = str(key).strip().lower()
            if key == "custom_fields":
                if not isinstance(value, dict):
                    raise ImportFormatError(_("custom_fields must be an object."))
                for cf_key, cf_value in value.items():
                    flat[f"cf_{str(cf_key).lower()}"] = _text(cf_value)
            else:
                flat[key] = _text(value)
        for key in flat:
            if key not in headers:
                headers.append(key)
        rows.append(flat)
    return headers, rows


def detect_format(filename, raw):
    name = (filename or "").lower()
    for fmt in FORMATS:
        if name.endswith("." + fmt):
            return fmt
    if raw[:2] == b"PK":
        return "xlsx"
    if raw.lstrip()[:1] in (b"{", b"["):
        return "json"
    return "csv"


def read(filename, raw):
    if len(raw) > MAX_BYTES:
        raise ImportFormatError(_("The file is larger than 1 MB."))
    fmt = detect_format(filename, raw)
    reader = {"csv": _read_csv, "xlsx": _read_xlsx, "json": _read_json}[fmt]
    headers, rows = reader(raw)
    headers = [str(h).strip().lower() for h in headers if str(h or "").strip()]
    rows = [{str(k).strip().lower(): (v or "").strip() for k, v in r.items() if k} for r in rows]
    return fmt, headers, [r for r in rows if any(v for v in r.values())]


# -------------------------------------------------------------------- validation
class RowResult:
    def __init__(self, line, data):
        self.line = line
        self.data = data
        self.errors = []


def _split(value):
    return [v.strip() for v in (value or "").split(";") if v.strip()]


def parse(project, raw_bytes, filename=""):
    """
    Return (parsed, errors, fmt). `parsed` rows are ready for create_issue();
    `errors` lists every problem with its line number (spreadsheet/CSV line,
    where line 1 is the header; JSON item numbers start at 2 to match).
    """
    fmt, headers, rows = read(filename, raw_bytes)
    if not headers:
        raise ImportFormatError(_("The file is empty."))
    missing = REQUIRED - set(headers)
    if missing:
        raise ImportFormatError(_("Missing required column(s): %(cols)s") % {"cols": ", ".join(sorted(missing))})
    unknown = [h for h in headers if h not in COLUMNS and not h.startswith("cf_")]
    if unknown:
        raise ImportFormatError(_("Unknown column(s): %(cols)s") % {"cols": ", ".join(unknown)})
    if not rows:
        raise ImportFormatError(_("The file has no issue rows."))
    if len(rows) > MAX_ROWS:
        raise ImportFormatError(_("At most %(n)s rows per import.") % {"n": MAX_ROWS})

    members = {}
    for u in project.members_qs():
        members[u.username.lower()] = u
        members[u.email.lower()] = u
    epics = {i.key: i for i in project.issues.filter(issue_type=IssueType.EPIC)}
    tasks = {i.key: i for i in project.issues.all()}
    sprints = {s.name.lower(): s for s in Sprint.objects.filter(project=project).exclude(state=Sprint.State.CLOSED)}
    labels = {l.name.lower(): l for l in project.labels.all()}
    components = {c.name.lower(): c for c in project.components.all()}
    versions = {v.name.lower(): v for v in project.versions.all()}
    cf_defs = {d.key: d for d in project.custom_fields.all()}

    parsed, errors = [], []
    first_line = 2  # line 1 is the header row (CSV/Excel); JSON items use the same numbering
    for n, data in enumerate(rows, start=first_line):
        row = RowResult(n, {})

        def fail(field, msg):
            row.errors.append(f"{field}: {msg}")

        itype = data.get("issue_type", "").lower()
        if itype not in IssueType.values:
            fail("issue_type", _("use one of: %(v)s") % {"v": ", ".join(IssueType.values)})
        title = data.get("title", "")
        if not title:
            fail("title", _("required"))
        if len(title) > 255:
            fail("title", _("at most 255 characters"))

        priority = (data.get("priority") or "medium").lower()
        if priority not in Priority.values:
            fail("priority", _("use one of: %(v)s") % {"v": ", ".join(Priority.values)})

        assignee = None
        if data.get("assignee"):
            assignee = members.get(data["assignee"].lower())
            if assignee is None:
                fail("assignee", _("%(v)s is not a member of this project") % {"v": data["assignee"]})

        epic = None
        if data.get("epic"):
            epic = epics.get(data["epic"].upper())
            if epic is None:
                fail("epic", _("no epic %(v)s in this project") % {"v": data["epic"]})

        parent = None
        if data.get("parent"):
            parent = tasks.get(data["parent"].upper())
            if parent is None:
                fail("parent", _("no issue %(v)s in this project") % {"v": data["parent"]})
        if itype == IssueType.SUBTASK and parent is None:
            fail("parent", _("a sub-task needs a parent issue key"))

        sprint = None
        if data.get("sprint"):
            sprint = sprints.get(data["sprint"].lower())
            if sprint is None:
                fail("sprint", _("no open sprint named %(v)s") % {"v": data["sprint"]})

        story_points = None
        if data.get("story_points"):
            try:
                story_points = int(float(data["story_points"]))
                if not 0 <= story_points <= 1000:
                    raise ValueError
            except ValueError:
                fail("story_points", _("whole number between 0 and 1000"))

        due_date = None
        if data.get("due_date"):
            try:
                due_date = datetime.date.fromisoformat(data["due_date"][:10])
            except ValueError:
                fail("due_date", _("use YYYY-MM-DD"))

        label_objs, component_objs, version_objs = [], [], []
        for name in _split(data.get("labels")):
            obj = labels.get(name.lower())
            if obj is None:
                fail("labels", _("no label %(v)s") % {"v": name})
            else:
                label_objs.append(obj)
        for name in _split(data.get("components")):
            obj = components.get(name.lower())
            if obj is None:
                fail("components", _("no component %(v)s") % {"v": name})
            else:
                component_objs.append(obj)
        for name in _split(data.get("fix_versions")):
            obj = versions.get(name.lower())
            if obj is None:
                fail("fix_versions", _("no version %(v)s") % {"v": name})
            else:
                version_objs.append(obj)

        cf_raw = {k[3:]: v for k, v in data.items() if k.startswith("cf_") and v}
        for key in cf_raw:
            if key not in cf_defs:
                fail(f"cf_{key}", _("unknown custom field"))
        custom = {}
        if not row.errors and itype in IssueType.values:
            try:
                custom = clean_custom_fields(project, itype, cf_raw)
            except ValidationError as exc:
                for key, msgs in exc.message_dict.items():
                    fail(f"cf_{key}", " ".join(msgs))

        if row.errors:
            errors.append(row)
            continue

        row.data = dict(
            issue_type=itype,
            title=title,
            description=data.get("description", ""),
            priority=priority,
            assignee=assignee,
            epic=epic,
            parent=parent,
            sprint=sprint,
            story_points=story_points,
            due_date=due_date,
            custom_fields=custom,
            _labels=label_objs,
            _components=component_objs,
            _versions=version_objs,
        )
        parsed.append(row)
    return parsed, errors, fmt


@transaction.atomic
def commit(project, user, parsed):
    created = []
    for row in parsed:
        data = dict(row.data)
        labels = data.pop("_labels")
        components = data.pop("_components")
        versions = data.pop("_versions")
        issue = services.create_issue(
            project, user, labels=labels, components=components, fix_versions=versions, **data
        )
        created.append(issue)
    return created
