import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import ApiKey
from apps.core.testing import ProjectFixtureMixin, make_issue, make_project
from apps.projects.models import ProjectRole


class ApiKeyModelTests(ProjectFixtureMixin, TestCase):
    def test_raw_key_is_not_stored(self):
        key, raw = ApiKey.issue(self.dev, "Laptop")
        self.assertTrue(raw.startswith("mpk_"))
        self.assertNotEqual(key.key_hash, raw)
        self.assertEqual(key.key_hash, ApiKey.hash_key(raw))
        self.assertNotIn(raw, [key.key_hash, key.prefix])
        self.assertEqual(key.prefix, raw[:12])

    def test_revoked_and_expired_keys_are_inactive(self):
        key, _raw = ApiKey.issue(self.dev, "Old")
        key.revoke()
        self.assertFalse(key.is_active)
        expired, _raw = ApiKey.issue(self.dev, "Expired", expires_at=timezone.now() - datetime.timedelta(minutes=1))
        self.assertFalse(expired.is_active)


class ApiKeyAuthTests(ProjectFixtureMixin, TestCase):
    def setUp(self):
        self.api = APIClient()
        self.key, self.raw = ApiKey.issue(self.dev, "Test")

    def auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_bearer_key_authenticates_as_owner(self):
        response = self.api.get("/api/v1/me/", **self.auth(self.raw))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], self.dev.email)

    def test_x_api_key_header_also_works(self):
        response = self.api.get("/api/v1/me/", HTTP_X_API_KEY=self.raw)
        self.assertEqual(response.status_code, 200)

    def test_wrong_or_revoked_key_gets_401_with_error_body(self):
        response = self.api.get("/api/v1/me/", **self.auth("mpk_nope"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.json())
        self.key.revoke()
        response = self.api.get("/api/v1/me/", **self.auth(self.raw))
        self.assertEqual(response.status_code, 401)

    def test_key_of_deactivated_user_stops_working(self):
        self.dev.is_active = False
        self.dev.save()
        response = self.api.get("/api/v1/me/", **self.auth(self.raw))
        self.assertEqual(response.status_code, 401)

    def test_last_used_is_recorded(self):
        self.api.get("/api/v1/me/", **self.auth(self.raw))
        self.key.refresh_from_db()
        self.assertIsNotNone(self.key.last_used_at)

    def test_key_gets_owners_project_permissions(self):
        # dev is a member of TST - can read. The outsider's key can't see TST.
        response = self.api.get("/api/v1/projects/TST/issues/", **self.auth(self.raw))
        self.assertEqual(response.status_code, 200)
        out_key, out_raw = ApiKey.issue(self.outsider, "Outsider")
        response = self.api.get("/api/v1/projects/TST/issues/", **self.auth(out_raw))
        self.assertEqual(response.status_code, 404)

    def test_read_only_key_cannot_write(self):
        ro, ro_raw = ApiKey.issue(self.dev, "Reader", read_only=True)
        self.assertEqual(self.api.get("/api/v1/projects/TST/issues/", **self.auth(ro_raw)).status_code, 200)
        response = self.api.post(
            "/api/v1/projects/TST/issues/", {"title": "x", "issue_type": "task"}, format="json", **self.auth(ro_raw)
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "permission_denied")

    def test_write_key_creates_tickets(self):
        response = self.api.post(
            "/api/v1/projects/TST/issues/", {"title": "From Claude", "issue_type": "task"}, format="json", **self.auth(self.raw)
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["reporter"], self.dev.pk)


class IssueSearchTests(ProjectFixtureMixin, TestCase):
    def test_my_issues_across_projects_respect_membership(self):
        mine = make_issue(self.project, self.dev, title="Mine", assignee=self.dev)
        make_issue(self.project, self.pm, title="Not mine")
        other = make_project("OTH", members=[(self.pm, ProjectRole.PROJECT_MANAGER)])
        make_issue(other, self.pm, title="Other project", assignee=self.dev)  # dev is not a member
        _key, raw = ApiKey.issue(self.dev, "Search")
        api = APIClient()
        response = api.get("/api/v1/issues/?assignee=me", HTTP_AUTHORIZATION=f"Bearer {raw}")
        self.assertEqual(response.status_code, 200)
        titles = [i["title"] for i in response.json()["results"]]
        self.assertEqual(titles, ["Mine"])
        self.assertEqual(response.json()["results"][0]["key"], mine.key)

    def test_open_filter_excludes_done_per_project(self):
        done_issue = make_issue(self.project, self.dev, title="Finished")
        from apps.issues import services

        for st in ("in_progress", "in_review", "done"):
            services.transition_issue(done_issue, self.dev, st)
        make_issue(self.project, self.dev, title="Still open")
        _key, raw = ApiKey.issue(self.dev, "Search")
        response = APIClient().get("/api/v1/issues/?open=true", HTTP_AUTHORIZATION=f"Bearer {raw}")
        titles = [i["title"] for i in response.json()["results"]]
        self.assertIn("Still open", titles)
        self.assertNotIn("Finished", titles)


class ApiKeyProfileTests(ProjectFixtureMixin, TestCase):
    def test_create_shows_raw_key_once_and_stores_only_hash(self):
        self.client.force_login(self.dev)
        response = self.client.post("/accounts/profile/", {"action": "create_key", "name": "Claude", "read_only": ""})
        self.assertEqual(response.status_code, 200)
        raw = response.context["new_key"]
        self.assertTrue(raw.startswith("mpk_"))
        self.assertContains(response, raw)
        key = ApiKey.objects.get(user=self.dev)
        self.assertEqual(key.key_hash, ApiKey.hash_key(raw))
        again = self.client.get("/accounts/profile/")
        self.assertNotContains(again, raw)

    def test_revoke_only_own_keys(self):
        mine, _raw = ApiKey.issue(self.dev, "Mine")
        theirs, _raw = ApiKey.issue(self.outsider, "Theirs")
        self.client.force_login(self.dev)
        self.client.post("/accounts/profile/", {"action": "revoke_key", "key_id": theirs.pk})
        theirs.refresh_from_db()
        self.assertIsNone(theirs.revoked_at)
        self.client.post("/accounts/profile/", {"action": "revoke_key", "key_id": mine.pk})
        mine.refresh_from_db()
        self.assertIsNotNone(mine.revoked_at)

    def test_expiry_in_days(self):
        self.client.force_login(self.dev)
        self.client.post("/accounts/profile/", {"action": "create_key", "name": "Short", "expires_in_days": 7})
        key = ApiKey.objects.get(user=self.dev, name="Short")
        self.assertIsNotNone(key.expires_at)
        self.assertTrue(timezone.now() + datetime.timedelta(days=6) < key.expires_at)
