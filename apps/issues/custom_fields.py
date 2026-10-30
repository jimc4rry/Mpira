"""
Validation/coercion for per-project custom fields, shared by the HTML issue
form and the REST API so both enforce exactly the same rules.
"""

import datetime

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import gettext as _

from .models import CustomFieldDefinition

FieldType = CustomFieldDefinition.FieldType


def definitions_for(project, issue_type=None):
    qs = CustomFieldDefinition.objects.filter(project=project)
    if issue_type:
        qs = qs.filter(Q(issue_type="") | Q(issue_type=issue_type))
    return list(qs)


def applies_to(defn, issue_type):
    return not defn.issue_type or defn.issue_type == issue_type


def form_field_for(defn):
    common = {"label": defn.name, "required": False}
    if defn.field_type == FieldType.NUMBER:
        return forms.DecimalField(**common)
    if defn.field_type == FieldType.DATE:
        return forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), **common)
    if defn.field_type == FieldType.SELECT:
        choices = [("", "---------")] + [(o, o) for o in defn.option_list]
        return forms.ChoiceField(choices=choices, **common)
    if defn.field_type == FieldType.CHECKBOX:
        return forms.BooleanField(**common)
    return forms.CharField(max_length=500, **common)


def coerce_value(defn, value):
    """Turn a raw (form- or JSON-supplied) value into its stored JSON form."""
    if value in (None, ""):
        return None
    if defn.field_type == FieldType.NUMBER:
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValidationError(_("Enter a number."))
        return int(number) if number.is_integer() else number
    if defn.field_type == FieldType.DATE:
        if isinstance(value, datetime.date):
            return value.isoformat()
        try:
            return datetime.date.fromisoformat(str(value)).isoformat()
        except ValueError:
            raise ValidationError(_("Enter a date as YYYY-MM-DD."))
    if defn.field_type == FieldType.SELECT:
        if value not in defn.option_list:
            raise ValidationError(
                _("Choose one of: %(options)s.") % {"options": ", ".join(defn.option_list)}
            )
        return value
    if defn.field_type == FieldType.CHECKBOX:
        if isinstance(value, bool):
            return value
        return str(value).lower() in ("1", "true", "yes", "on")
    value = str(value)
    if len(value) > 500:
        raise ValidationError(_("At most 500 characters."))
    return value


def clean_custom_fields(project, issue_type, raw):
    """
    Validate a {key: value} dict against the project's definitions.
    Returns the cleaned dict; raises ValidationError({key: [msg]}) on failure.
    Unknown keys are rejected so API typos don't silently disappear.
    """
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ValidationError({"custom_fields": [_("Must be an object.")]})
    defs = {d.key: d for d in definitions_for(project)}
    errors, cleaned = {}, {}
    for key in raw:
        if key not in defs:
            errors[key] = [_("Unknown custom field.")]
    for key, defn in defs.items():
        if not applies_to(defn, issue_type):
            continue
        try:
            value = coerce_value(defn, raw.get(key))
        except ValidationError as exc:
            errors[key] = exc.messages
            continue
        if defn.required and value in (None, "", False):
            errors[key] = [_("This field is required.")]
            continue
        if value is not None:
            cleaned[key] = value
    if errors:
        raise ValidationError(errors)
    return cleaned


def display_values(issue):
    """[(definition, value)] for the issue detail sidebar."""
    out = []
    for defn in definitions_for(issue.project, issue.issue_type):
        value = issue.custom_fields.get(defn.key)
        if value is not None and value != "":
            if defn.field_type == FieldType.CHECKBOX:
                value = _("Yes") if value else _("No")
            out.append((defn, value))
    return out
