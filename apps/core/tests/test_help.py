from django.test import TestCase

from apps.core.testing import make_user


class HelpPageTests(TestCase):
    def test_guide_requires_login(self):
        response = self.client.get("/help/")
        self.assertEqual(response.status_code, 302)

    def test_guide_shows_this_servers_api_address(self):
        user = make_user()
        self.client.force_login(user)
        response = self.client.get("/help/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "/api/v1/")
        self.assertContains(response, "mpk_")
        self.assertContains(response, "tools/mpira-mcp")
