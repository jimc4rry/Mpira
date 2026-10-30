from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from apps.issues.models import CustomFieldDefinition

from .models import Component, Label, Project, ProjectMembership, Version

User = get_user_model()


class ProjectScopedForm(forms.ModelForm):
    """
    For models with unique_together=(project, <field>): the project isn't a
    form field, so Django skips that check - do it here instead of letting
    the DB raise an IntegrityError.
    """

    unique_field = "name"

    def __init__(self, *args, project=None, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        value = cleaned.get(self.unique_field)
        if value and self.project is not None:
            qs = self._meta.model.objects.filter(project=self.project, **{self.unique_field: value})
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                self.add_error(self.unique_field, _("Already exists in this project."))
        return cleaned


class ProjectCreateForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "key", "description", "lead"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lead"].queryset = User.objects.filter(is_active=True)
        self.fields["key"].widget.attrs.update({"style": "text-transform:uppercase", "maxlength": 10})

    def clean_key(self):
        return self.cleaned_data["key"].upper()


class ProjectEditForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "description", "lead", "is_archived"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lead"].queryset = User.objects.filter(is_active=True)


class MembershipForm(forms.ModelForm):
    class Meta:
        model = ProjectMembership
        fields = ["user", "role"]

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        existing = project.memberships.values_list("user_id", flat=True) if project else []
        self.fields["user"].queryset = User.objects.filter(is_active=True).exclude(pk__in=existing)
        self.fields["user"].label = _("User")


class ComponentForm(ProjectScopedForm):
    class Meta:
        model = Component
        fields = ["name", "description"]


class VersionForm(ProjectScopedForm):
    class Meta:
        model = Version
        fields = ["name", "description", "release_date", "status"]
        widgets = {"release_date": forms.DateInput(attrs={"type": "date"})}


class LabelForm(ProjectScopedForm):
    class Meta:
        model = Label
        fields = ["name", "color"]
        widgets = {"color": forms.TextInput(attrs={"type": "color"})}


class CustomFieldForm(ProjectScopedForm):
    unique_field = "key"

    class Meta:
        model = CustomFieldDefinition
        fields = ["name", "key", "field_type", "issue_type", "options", "required"]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("field_type") == CustomFieldDefinition.FieldType.SELECT and not [
            o for o in (cleaned.get("options") or "").split(",") if o.strip()
        ]:
            self.add_error("options", _("Select fields need at least one option."))
        return cleaned
