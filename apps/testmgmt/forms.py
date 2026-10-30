from django import forms
from django.forms import modelformset_factory
from django.utils.translation import gettext_lazy as _

from apps.issues.models import IssueType

from .models import TestExecution, TestPlan, TestStep


class TestsField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f"{obj.key} {obj.title}"


class TestPlanForm(forms.ModelForm):
    tests = TestsField(queryset=None, required=False, widget=forms.CheckboxSelectMultiple, label=_("Tests"))

    class Meta:
        model = TestPlan
        fields = ["name", "description", "fix_version", "tests"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3})}

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tests"].queryset = project.issues.filter(issue_type=IssueType.TEST).order_by("number")
        self.fields["fix_version"].queryset = project.versions.all()


class TestExecutionForm(forms.ModelForm):
    tests = TestsField(
        queryset=None,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label=_("Additional tests"),
        help_text=_("Tests from the selected plan are included automatically."),
    )

    class Meta:
        model = TestExecution
        fields = ["name", "plan", "environment", "fix_version"]

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["plan"].queryset = project.test_plans.all()
        self.fields["fix_version"].queryset = project.versions.all()
        self.fields["tests"].queryset = project.issues.filter(issue_type=IssueType.TEST).order_by("number")

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("plan") and not cleaned.get("tests"):
            raise forms.ValidationError(_("Pick a test plan or at least one test."))
        return cleaned


TestStepFormSet = modelformset_factory(
    TestStep,
    fields=["action", "data", "expected_result"],
    widgets={
        "action": forms.Textarea(attrs={"rows": 2}),
        "data": forms.Textarea(attrs={"rows": 2}),
        "expected_result": forms.Textarea(attrs={"rows": 2}),
    },
    extra=2,
    can_delete=True,
)
