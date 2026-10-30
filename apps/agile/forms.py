from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Sprint


class SprintForm(forms.ModelForm):
    class Meta:
        model = Sprint
        fields = ["name", "goal", "start_date", "end_date"]
        widgets = {
            "goal": forms.Textarea(attrs={"rows": 2}),
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", _("The end date must be after the start date."))
        return cleaned


class StartSprintForm(forms.Form):
    start_date = forms.DateField(label=_("Start date"), widget=forms.DateInput(attrs={"type": "date"}))
    end_date = forms.DateField(label=_("End date"), widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", _("The end date must be after the start date."))
        return cleaned
