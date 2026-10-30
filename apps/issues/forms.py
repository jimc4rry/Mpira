from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.agile.models import Sprint

from .custom_fields import applies_to, clean_custom_fields, definitions_for, form_field_for
from .models import Comment, Issue, IssueLink, IssueType


class IssueForm(forms.ModelForm):
    class Meta:
        model = Issue
        fields = [
            "issue_type",
            "title",
            "description",
            "priority",
            "assignee",
            "parent",
            "epic",
            "sprint",
            "story_points",
            "start_date",
            "due_date",
            "labels",
            "components",
            "fix_versions",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 8, "data-markdown": "1"}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
            "labels": forms.CheckboxSelectMultiple(),
            "components": forms.CheckboxSelectMultiple(),
            "fix_versions": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, project, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)
        f = self.fields
        f["assignee"].queryset = project.members_qs()
        others = project.issues.exclude(pk=self.instance.pk) if self.instance.pk else project.issues.all()
        f["parent"].queryset = others.exclude(issue_type__in=[IssueType.SUBTASK, IssueType.EPIC]).order_by("number")
        f["epic"].queryset = others.filter(issue_type=IssueType.EPIC).order_by("number")
        # Keep the issue's current (possibly closed) sprint selectable on edit.
        f["sprint"].queryset = Sprint.objects.filter(project=project).filter(
            ~Q(state=Sprint.State.CLOSED) | Q(pk=self.instance.sprint_id or 0)
        )
        f["labels"].queryset = project.labels.all()
        f["components"].queryset = project.components.all()
        f["fix_versions"].queryset = project.versions.all()
        for name in ("parent", "epic"):
            f[name].label_from_instance = lambda obj: f"{obj.key} {obj.title}"
        f["parent"].help_text = _("Required for sub-tasks.")

        self.custom_defs = definitions_for(project)
        for defn in self.custom_defs:
            field = form_field_for(defn)
            if defn.required:
                field.label = f"{defn.name} *"
            field.widget.attrs["data-issue-type"] = defn.issue_type
            name = f"cf_{defn.key}"
            f[name] = field
            if self.instance.pk:
                f[name].initial = (self.instance.custom_fields or {}).get(defn.key)

    def custom_field_names(self):
        return [f"cf_{d.key}" for d in self.custom_defs]

    def standard_fields(self):
        return [self[name] for name in self.Meta.fields]

    def custom_bound_fields(self):
        return [self[name] for name in self.custom_field_names()]

    def clean(self):
        cleaned = super().clean()
        issue_type = cleaned.get("issue_type")
        if issue_type == IssueType.SUBTASK and not cleaned.get("parent"):
            self.add_error("parent", _("A sub-task needs a parent issue."))
        if issue_type != IssueType.SUBTASK:
            cleaned["parent"] = None
        if issue_type == IssueType.EPIC:
            cleaned["epic"] = None
        raw = {}
        for defn in self.custom_defs:
            value = cleaned.get(f"cf_{defn.key}")
            if applies_to(defn, issue_type) and value not in (None, ""):
                raw[defn.key] = value
        try:
            self.cleaned_custom_fields = clean_custom_fields(self.project, issue_type, raw)
        except ValidationError as exc:
            for key, msgs in exc.message_dict.items():
                self.add_error(f"cf_{key}" if f"cf_{key}" in self.fields else None, msgs)
        return cleaned

    def save(self, commit=True):
        issue = super().save(commit=False)
        issue.custom_fields = getattr(self, "cleaned_custom_fields", {})
        if commit:
            issue.save()
            self.save_m2m()
        return issue


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(
                attrs={"rows": 3, "placeholder": _("Add a comment… use @handle to mention someone")}
            )
        }
        labels = {"body": ""}


class AttachmentForm(forms.Form):
    file = forms.FileField(label=_("File"))

    def clean_file(self):
        f = self.cleaned_data["file"]
        if f.size > settings.MAX_ATTACHMENT_SIZE:
            raise ValidationError(
                _("Files can be at most %(mb)s MB.") % {"mb": settings.MAX_ATTACHMENT_SIZE // (1024 * 1024)}
            )
        return f


class LinkForm(forms.Form):
    DIRECTION_CHOICES = [("out", _("this issue →")), ("in", _("← this issue"))]
    link_type = forms.ChoiceField(label=_("Link type"), choices=IssueLink.LinkType.choices)
    target_key = forms.CharField(label=_("Issue key"), max_length=20, widget=forms.TextInput(attrs={"placeholder": "MPR-12"}))
