from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _


class Role(models.TextChoices):
    """
    Workspace-wide roles. A user's role inside a specific project comes from
    projects.ProjectMembership and may differ (e.g. a Developer who is only a
    Viewer on another team's project) - see apps.projects.permissions.
    """

    ADMIN = "admin", _("Admin")
    PROJECT_MANAGER = "pm", _("Project Manager")
    DEVELOPER = "developer", _("Developer")
    TESTER = "tester", _("Tester")
    VIEWER = "viewer", _("Viewer")


class MpiraUserManager(UserManager):
    """Email is the login identifier; username is kept as the @mention handle."""

    def _create_user(self, username, email, password, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email).lower()
        if not username:
            username = email.split("@")[0]
        return super()._create_user(username, email, password, **extra_fields)

    def create_user(self, username=None, email=None, password=None, **extra_fields):
        return super().create_user(username, email, password, **extra_fields)

    def create_superuser(self, username=None, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", Role.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    email = models.EmailField(_("email address"), unique=True)
    role = models.CharField(_("Role"), max_length=20, choices=Role.choices, default=Role.DEVELOPER)
    language = models.CharField(
        _("Language"), max_length=8, choices=settings.LANGUAGES, default="en"
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    objects = MpiraUserManager()

    class Meta:
        ordering = ["first_name", "last_name", "username"]

    def __str__(self):
        return self.display_name

    @property
    def display_name(self):
        return self.get_full_name() or self.username

    @property
    def initials(self):
        parts = [p for p in self.display_name.replace(".", " ").split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "?"

    @property
    def is_workspace_admin(self):
        return self.is_superuser or self.role == Role.ADMIN

    @classmethod
    def seats_available(cls, exclude_pk=None):
        active = cls.objects.filter(is_active=True)
        if exclude_pk:
            active = active.exclude(pk=exclude_pk)
        return active.count() < settings.MAX_ACTIVE_USERS

    def save(self, *args, **kwargs):
        self.email = (self.email or "").lower()
        # Hard guard for the seat limit - forms check it too, with a friendlier
        # message, but this catches the admin, the API and management commands.
        if self.is_active and not self.seats_available(exclude_pk=self.pk):
            was_active = self.pk and type(self).objects.filter(pk=self.pk, is_active=True).exists()
            if not was_active:
                raise ValidationError(
                    _("The workspace is limited to %(n)s active users.")
                    % {"n": settings.MAX_ACTIVE_USERS}
                )
        super().save(*args, **kwargs)


class ApiKey(models.Model):
    """
    A personal access token for the REST API (and tools such as Claude via the
    Mpira MCP server). The raw key is shown once at creation; only its SHA-256
    hash is stored. A key acts as its owner, with the owner's project roles.
    """

    PREFIX = "mpk_"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(_("Name"), max_length=80)
    prefix = models.CharField(max_length=12)  # first chars of the key, for identification
    key_hash = models.CharField(max_length=64, unique=True)
    read_only = models.BooleanField(_("Read only"), default=False)
    expires_at = models.DateTimeField(_("Expires"), null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @staticmethod
    def hash_key(raw):
        import hashlib

        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @classmethod
    def issue(cls, user, name, *, read_only=False, expires_at=None):
        import secrets

        raw = cls.PREFIX + secrets.token_urlsafe(32)
        key = cls.objects.create(
            user=user,
            name=name,
            prefix=raw[:12],
            key_hash=cls.hash_key(raw),
            read_only=read_only,
            expires_at=expires_at,
        )
        return key, raw

    @property
    def is_active(self):
        from django.utils import timezone

        if self.revoked_at:
            return False
        return not (self.expires_at and self.expires_at <= timezone.now())

    def revoke(self):
        from django.utils import timezone

        self.revoked_at = timezone.now()
        self.save(update_fields=["revoked_at"])
