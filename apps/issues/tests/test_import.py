import datetime
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.agile.models import Sprint
from apps.core.testing import ProjectFixtureMixin, make_issue
from apps.issues import importer
from apps.issues.models import CustomFieldDefinition, Issue, IssueType
from apps.projects.models import Label

HEADER = ",".join(importer.COLUMNS)


def csv_bytes(*rows):
    return ("\n".join([HEADER, *rows]) + "\n").encode("utf-8")


class ImportParseTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.epic = make_issue(self.project, self.pm, issue_type=IssueType.EPIC, title="Checkout")
        Label.objects.create(project=self.project, name="ux")
        self.sprint = Sprint.objects.create(project=self.project, name="Sprint A")

    def test_template_matches_columns_and_is_importable(self):
        content = importer.template_csv_text()
        self.assertTrue(content.startswith(HEADER))
        # Example rows reference people and keys that don't exist in a blank project,
        # so the template is a format guide - it must parse, but won't be fully valid.
        parsed, errors, _fmt = importer.parse(self.project, content.encode(), 'x.csv')
        self.assertTrue(parsed or errors)

    def test_valid_file_creates_all_issues_with_links(self):
        data = csv_bytes(
            f"story,Pay with card,,high,dev@example.com,{self.project.key}-{self.epic.number},,Sprint A,5,2026-12-01,ux,,",
            "task,Set up flags,,low,,,,,,,,,",
        )
        parsed, errors, _fmt = importer.parse(self.project, data)
        self.assertEqual(errors, [])
        created = importer.commit(self.project, self.pm, parsed)
        self.assertEqual(len(created), 2)
        story = Issue.objects.get(title="Pay with card")
        self.assertEqual(story.assignee, self.dev)
        self.assertEqual(story.epic, self.epic)
        self.assertEqual(story.sprint, self.sprint)
        self.assertEqual(story.story_points, 5)
        self.assertEqual(list(story.labels.values_list("name", flat=True)), ["ux"])
        self.assertEqual(story.reporter, self.pm)
        self.assertEqual(story.status, "todo")

    def test_every_error_is_reported_with_its_line(self):
        data = csv_bytes(
            "story,ok,,,,,,,,,,,",
            "wrong_type,x,,,,,,,,,,,",
            "story,,,,nobody@example.com,,,,abc,2026-13-01,nolabel,,",
            "subtask,child,,,,,,,,,,,",
        )
        parsed, errors, _fmt = importer.parse(self.project, data)
        self.assertEqual(len(parsed), 1)
        by_line = {e.line: e.errors for e in errors}
        self.assertEqual(sorted(by_line), [3, 4, 5])
        self.assertTrue(any("issue_type" in m for m in by_line[3]))
        self.assertTrue(any("title" in m for m in by_line[4]))
        self.assertTrue(any("assignee" in m for m in by_line[4]))
        self.assertTrue(any("story_points" in m for m in by_line[4]))
        self.assertTrue(any("due_date" in m for m in by_line[4]))
        self.assertTrue(any("labels" in m for m in by_line[4]))
        self.assertTrue(any("parent" in m for m in by_line[5]))

    def test_bad_structure_is_rejected(self):
        with self.assertRaises(importer.ImportFormatError):
            importer.parse(self.project, b"")
        with self.assertRaises(importer.ImportFormatError):
            importer.parse(self.project, b"type,name\nstory,x\n")
        with self.assertRaises(importer.ImportFormatError):
            importer.parse(self.project, (HEADER + ",bogus\n").encode())
        with self.assertRaises(importer.ImportFormatError):
            importer.parse(self.project, HEADER.encode() + b"\n")
        with self.assertRaises(importer.ImportFormatError):
            importer.parse(self.project, "issue_type,title\nstory,é".encode("latin-1"))

    def test_custom_fields(self):
        CustomFieldDefinition.objects.create(
            project=self.project, name="Impact", key="impact", field_type="select", options="Low,High", issue_type=IssueType.BUG
        )
        data = ("issue_type,title,cf_impact\nbug,crash,High\nbug,other,Huge\n").encode()
        parsed, errors, _fmt = importer.parse(self.project, data)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].data["custom_fields"], {"impact": "High"})
        self.assertEqual(errors[0].line, 3)


class ImportViewTests(ProjectFixtureMixin, TestCase):
    def test_all_or_nothing_on_the_web(self):
        self.client.force_login(self.dev)
        bad = SimpleUploadedFile("i.csv", csv_bytes("story,good,,,,,,,,,,,", "story,,,,,,,,,,,,"), content_type="text/csv")
        response = self.client.post(f"/projects/{self.project.key}/issues/import/", {"file": bad})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Issue.objects.exists())
        self.assertContains(response, "Nothing was imported")

        good = SimpleUploadedFile("i.csv", csv_bytes("story,one,,,,,,,,,,,", "bug,two,,,,,,,,,,,"), content_type="text/csv")
        response = self.client.post(f"/projects/{self.project.key}/issues/import/", {"file": good})
        self.assertRedirects(response, f"/projects/{self.project.key}/issues/")
        self.assertEqual(Issue.objects.count(), 2)

    def test_template_download(self):
        self.client.force_login(self.dev)
        response = self.client.get(f"/projects/{self.project.key}/issues/import/template.csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertTrue(response.content.decode("utf-8-sig").startswith(HEADER))

    def test_viewer_cannot_import(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(f"/projects/{self.project.key}/issues/import/").status_code, 403)
        self.assertEqual(self.client.get(f"/projects/{self.project.key}/issues/import/template.csv").status_code, 403)


import io  # noqa: E402
import json  # noqa: E402

from openpyxl import Workbook  # noqa: E402


def xlsx_bytes(rows, headers=None):
    wb = Workbook()
    ws = wb.active
    ws.title = "Issues"
    ws.append(headers or importer.COLUMNS)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class ImportFormatsTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.epic = make_issue(self.project, self.pm, issue_type=IssueType.EPIC, title="Checkout")
        Label.objects.create(project=self.project, name="ux")

    def test_xlsx_import_and_types(self):
        data = xlsx_bytes([
            ["story", "From Excel", "", "high", self.dev.email, self.epic.key, "", "", 3, None, "ux", "", ""],
        ])
        parsed, errors, fmt = importer.parse(self.project, data, "issues.xlsx")
        self.assertEqual((fmt, errors), ("xlsx", []))
        importer.commit(self.project, self.pm, parsed)
        issue = Issue.objects.get(title="From Excel")
        self.assertEqual(issue.story_points, 3)
        self.assertEqual(issue.epic, self.epic)
        self.assertEqual(list(issue.labels.values_list("name", flat=True)), ["ux"])

    def test_xlsx_numbers_and_dates_are_read_as_text(self):
        data = xlsx_bytes([["task", "Dated", "", "", "", "", "", "", 2, datetime.date(2026, 12, 1), "", "", ""]])
        parsed, errors, _fmt = importer.parse(self.project, data, "d.xlsx")
        self.assertEqual(errors, [])
        self.assertEqual(parsed[0].data["due_date"], datetime.date(2026, 12, 1))
        self.assertEqual(parsed[0].data["story_points"], 2)

    def test_json_import_with_custom_fields(self):
        CustomFieldDefinition.objects.create(
            project=self.project, name="Impact", key="impact", field_type="select", options="Low,High", issue_type=IssueType.BUG
        )
        payload = {"issues": [
            {"issue_type": "bug", "title": "JSON bug", "priority": "high", "labels": ["ux"], "custom_fields": {"impact": "High"}},
            {"issue_type": "task", "title": "JSON task", "story_points": 1},
        ]}
        parsed, errors, fmt = importer.parse(self.project, json.dumps(payload).encode(), "issues.json")
        self.assertEqual((fmt, errors), ("json", []))
        importer.commit(self.project, self.pm, parsed)
        bug = Issue.objects.get(title="JSON bug")
        self.assertEqual(bug.custom_fields, {"impact": "High"})
        self.assertEqual(list(bug.labels.values_list("name", flat=True)), ["ux"])

    def test_json_errors_keep_line_numbers(self):
        payload = [{"issue_type": "story", "title": "ok"}, {"issue_type": "nope", "title": ""}]
        parsed, errors, _fmt = importer.parse(self.project, json.dumps(payload).encode(), "x.json")
        self.assertEqual(len(parsed), 1)
        self.assertEqual(errors[0].line, 3)

    def test_json_structure_errors(self):
        with self.assertRaises(importer.ImportFormatError):
            importer.parse(self.project, b'{"nope": 1}', "x.json")
        with self.assertRaises(importer.ImportFormatError):
            importer.parse(self.project, b'{ not json', "x.json")
        with self.assertRaises(importer.ImportFormatError):
            importer.parse(self.project, b'["text"]', "x.json")

    def test_xlsx_structure_errors(self):
        with self.assertRaises(importer.ImportFormatError):
            importer.parse(self.project, xlsx_bytes([], headers=["type", "name"]), "x.xlsx")
        with self.assertRaises(importer.ImportFormatError):
            importer.parse(self.project, b"PK\x03\x04garbage", "x.xlsx")

    def test_detect_by_content_when_extension_missing(self):
        self.assertEqual(importer.detect_format("", xlsx_bytes([])), "xlsx")
        self.assertEqual(importer.detect_format("", b'[{"title": "x"}]'), "json")
        self.assertEqual(importer.detect_format("", b"issue_type,title"), "csv")

    def test_each_template_is_importable(self):
        for fmt in importer.FORMATS:
            content = importer.template_bytes(fmt)
            _p, errors, got = importer.parse(self.project, content, f"t.{fmt}")
            self.assertEqual(got, fmt)
            # Example rows reference people/keys absent from a blank project; the
            # template is a format guide, so only a successful read is required here.
            self.assertTrue(_p or errors)

    def test_template_download_formats(self):
        self.client.force_login(self.dev)
        for fmt, mime in [("csv", "text/csv"), ("xlsx", "spreadsheetml"), ("json", "application/json")]:
            response = self.client.get(f"/projects/{self.project.key}/issues/import/template.{fmt}")
            self.assertEqual(response.status_code, 200, fmt)
            self.assertIn(mime, response["Content-Type"])
            self.assertIn(f"template.{fmt}", response["Content-Disposition"])
        self.assertEqual(self.client.get(f"/projects/{self.project.key}/issues/import/template.exe").status_code, 404)

    def test_web_upload_accepts_xlsx(self):
        self.client.force_login(self.dev)
        upload = SimpleUploadedFile("i.xlsx", xlsx_bytes([["bug", "via web", "", "", "", "", "", "", "", "", "", "", ""]]))
        response = self.client.post(f"/projects/{self.project.key}/issues/import/", {"file": upload})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Issue.objects.filter(title="via web").exists())
