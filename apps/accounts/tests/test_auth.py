from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.core.testing import PASSWORD, make_user


class LoginTests(TestCase):
    def setUp(self):
        self.user = make_user(email="Someone@Example.com", username="someone")

    def test_email_is_normalized_to_lowercase(self):
        self.assertEqual(self.user.email, "someone@example.com")

    def test_login_with_email_and_password(self):
        response = self.client.post(
            reverse("accounts:login"), {"username": "SOMEONE@example.com", "password": PASSWORD}
        )
        self.assertRedirects(response, reverse("core:dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_wrong_password_is_rejected(self):
        response = self.client.post(reverse("accounts:login"), {"username": "someone@example.com", "password": "nope"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()
        self.assertFalse(self.client.login(username="someone@example.com", password=PASSWORD))

    def test_pages_require_login(self):
        for url in ["/", "/projects/", "/accounts/profile/"]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn(reverse("accounts:login"), response["Location"])

    def test_logout(self):
        self.client.force_login(self.user)
        self.client.post(reverse("accounts:logout"))
        self.assertNotIn("_auth_user_id", self.client.session)


class UserManagementTests(TestCase):
    def setUp(self):
        self.admin = make_user(Role.ADMIN, email="admin@example.com", username="admin")
        self.dev = make_user(Role.DEVELOPER)

    def test_only_admins_reach_user_management(self):
        self.client.force_login(self.dev)
        self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 404)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("accounts:user_list")).status_code, 200)

    def test_admin_creates_user(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:user_create"),
            {
                "email": "New@Example.com",
                "username": "newbie",
                "first_name": "New",
                "last_name": "Person",
                "role": Role.TESTER,
                "language": "el",
                "password": "Another-str0ng-pass",
            },
        )
        self.assertRedirects(response, reverse("accounts:user_list"))
        user = User.objects.get(email="new@example.com")
        self.assertEqual(user.role, Role.TESTER)
        self.assertTrue(user.check_password("Another-str0ng-pass"))

    def test_weak_password_is_rejected(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:user_create"),
            {"email": "x@example.com", "username": "x", "role": Role.DEVELOPER, "language": "en", "password": "123"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="x@example.com").exists())

    @override_settings(MAX_ACTIVE_USERS=2)
    def test_seat_limit_is_enforced(self):
        with self.assertRaises(ValidationError):
            make_user()
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("accounts:user_create"),
            {"email": "y@example.com", "username": "y", "role": Role.DEVELOPER, "language": "en", "password": "Another-str0ng-pass"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="y@example.com").exists())

    def test_language_preference_is_saved_and_applied(self):
        self.client.force_login(self.dev)
        self.client.post(reverse("accounts:set_language"), {"language": "el", "next": "/"})
        self.dev.refresh_from_db()
        self.assertEqual(self.dev.language, "el")
        response = self.client.get("/")
        self.assertEqual(response["Content-Language"], "el")
