from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Page


class PageForm(forms.Form):
    title = forms.CharField(label=_("Title"), max_length=200)
    parent = forms.ModelChoiceField(label=_("Parent page"), queryset=Page.objects.none(), required=False)
    body = forms.CharField(
        label=_("Content"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 22, "data-markdown": "1", "class": "mono"}),
        help_text=_("Markdown. Embed issues with [[KEY-123]], mention people with @handle."),
    )
    change_note = forms.CharField(label=_("Change note"), max_length=200, required=False)

    def __init__(self, *args, space, page=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = space.pages.all()
        if page is not None and page.pk:
            # A page can't become a child of itself or of its own descendants.
            qs = qs.exclude(pk__in={page.pk} | page.descendant_ids())
        self.fields["parent"].queryset = qs
