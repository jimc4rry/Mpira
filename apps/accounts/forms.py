from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.utils.translation import gettext_lazy as _

from .models import User


def _seat_limit_error():
    return forms.ValidationError(
        _("The workspace is limited to %(n)s active users.") % {"n": settings.MAX_ACTIVE_USERS}
    )


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label=_("Email"),
        widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}),
    )

    error_messages = {
        "invalid_login": _("Wrong email or password."),
        "inactive": _("This account is inactive."),
    }

    def clean_username(self):
        return self.cleaned_data["username"].lower()


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "username", "language"]
        labels = {"username": _("Handle (for @mentions)")}


class UserCreateForm(forms.ModelForm):
    password = forms.CharField(
        label=_("Initial password"),
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text=_("Share it with the user privately; they can change it from their profile."),
    )

    class Meta:
        model = User
        fields = ["email", "username", "first_name", "last_name", "role", "language"]
        labels = {"username": _("Handle (for @mentions)")}

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError(_("A user with that email already exists."))
        return email

    def clean(self):
        cleaned = super().clean()
        if not User.seats_available():
            raise _seat_limit_error()
        password = cleaned.get("password")
        if password:
            probe = User(email=cleaned.get("email", ""), username=cleaned.get("username", ""))
            try:
                password_validation.validate_password(password, probe)
            except forms.ValidationError as exc:
                self.add_error("password", exc)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class UserAdminEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "username", "role", "is_active"]
        labels = {"username": _("Handle (for @mentions)"), "is_active": _("Active")}

    def clean(self):
        cleaned = super().clean()
        was_active = User.objects.filter(pk=self.instance.pk, is_active=True).exists()
        if cleaned.get("is_active") and not was_active and not User.seats_available():
            raise _seat_limit_error()
        return cleaned


class AdminSetPasswordForm(forms.Form):
    password = forms.CharField(
        label=_("New password"), widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self):
        password = self.cleaned_data["password"]
        password_validation.validate_password(password, self.user)
        return password


class ApiKeyForm(forms.Form):
    name = forms.CharField(label=_("Name"), max_length=80, help_text=_("What will use this key, e.g. Claude Desktop"))
    read_only = forms.BooleanField(label=_("Read only"), required=False, help_text=_("Can read tickets but never change them."))
    expires_in_days = forms.IntegerField(label=_("Expires after (days)"), required=False, min_value=1, max_value=3650)
