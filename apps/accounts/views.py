import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .decorators import workspace_admin_required
from .forms import (
    AdminSetPasswordForm,
    ApiKeyForm,
    EmailAuthenticationForm,
    ProfileForm,
    UserAdminEditForm,
    UserCreateForm,
)
from .models import ApiKey, User


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True


@require_POST
def set_language(request):
    """
    Language switcher. Logged-in users get the choice stored on their profile
    (applied by apps.core.middleware.UserLanguageMiddleware on every request);
    anonymous visitors get Django's standard language cookie.
    """
    lang = request.POST.get("language")
    next_url = request.POST.get("next") or "/"
    if not url_has_allowed_host_and_scheme(next_url, {request.get_host()}, request.is_secure()):
        next_url = "/"
    response = HttpResponseRedirect(next_url)
    if lang in dict(settings.LANGUAGES):
        if request.user.is_authenticated:
            request.user.language = lang
            request.user.save(update_fields=["language"])
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, lang, max_age=365 * 24 * 3600, samesite="Lax")
    return response


@login_required
def profile(request):
    profile_form = ProfileForm(instance=request.user)
    password_form = PasswordChangeForm(request.user)
    key_form = ApiKeyForm()
    new_key = None
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "change_password":
            password_form = PasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, _("Password changed."))
                return redirect("accounts:profile")
        elif action == "create_key":
            key_form = ApiKeyForm(request.POST)
            if key_form.is_valid():
                days = key_form.cleaned_data.get("expires_in_days")
                expires = timezone.now() + datetime.timedelta(days=days) if days else None
                _key, new_key = ApiKey.issue(
                    request.user,
                    key_form.cleaned_data["name"],
                    read_only=key_form.cleaned_data["read_only"],
                    expires_at=expires,
                )
                key_form = ApiKeyForm()
                messages.success(request, _("API key created. Copy it now - it won't be shown again."))
        elif action == "revoke_key":
            key = get_object_or_404(ApiKey, pk=request.POST.get("key_id"), user=request.user)
            key.revoke()
            messages.success(request, _("API key revoked."))
            return redirect("accounts:profile")
        else:
            profile_form = ProfileForm(request.POST, instance=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, _("Profile saved."))
                return redirect("accounts:profile")
    return render(
        request,
        "accounts/profile.html",
        {
            "profile_form": profile_form,
            "password_form": password_form,
            "key_form": key_form,
            "new_key": new_key,
            "api_keys": request.user.api_keys.all(),
            "api_base": request.build_absolute_uri("/api/v1/"),
        },
    )


@workspace_admin_required
def user_list(request):
    users = User.objects.all().order_by("-is_active", "email")
    active_count = User.objects.filter(is_active=True).count()
    return render(
        request,
        "accounts/user_list.html",
        {"users": users, "active_count": active_count, "max_users": settings.MAX_ACTIVE_USERS},
    )


@workspace_admin_required
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, _("User %(name)s created.") % {"name": user.display_name})
        return redirect("accounts:user_list")
    return render(request, "accounts/user_form.html", {"form": form, "is_new": True})


@workspace_admin_required
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = UserAdminEditForm(request.POST or None, instance=target)
    password_form = AdminSetPasswordForm(target)
    if request.method == "POST":
        if "set_password" in request.POST:
            password_form = AdminSetPasswordForm(target, request.POST)
            if password_form.is_valid():
                target.set_password(password_form.cleaned_data["password"])
                target.save(update_fields=["password"])
                messages.success(request, _("Password updated."))
                return redirect("accounts:user_edit", pk=target.pk)
            form = UserAdminEditForm(instance=target)
        elif form.is_valid():
            if target.pk == request.user.pk and not form.cleaned_data["is_active"]:
                messages.error(request, _("You cannot deactivate yourself."))
            else:
                try:
                    form.save()
                except ValidationError as exc:
                    messages.error(request, " ".join(exc.messages))
                else:
                    messages.success(request, _("User updated."))
                    return redirect("accounts:user_list")
    return render(
        request,
        "accounts/user_form.html",
        {"form": form, "password_form": password_form, "target": target, "is_new": False},
    )
