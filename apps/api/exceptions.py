"""
Every API error has the same shape:

    {"error": {"code": "validation_error", "message": "...", "details": {...}}}
"""

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from apps.agile.services import SprintError
from apps.issues.services import WorkflowError

CODES = {
    400: "validation_error",
    401: "not_authenticated",
    403: "permission_denied",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    415: "unsupported_media_type",
    429: "throttled",
}


class ConflictError(exceptions.APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Conflict."
    default_code = "conflict"


def _message(detail):
    if isinstance(detail, dict):
        if "detail" in detail:
            return str(detail["detail"])
        return "Invalid input."
    if isinstance(detail, list):
        return " ".join(str(d) for d in detail) or "Invalid input."
    return str(detail)


def api_exception_handler(exc, context):
    if isinstance(exc, (WorkflowError, SprintError)):
        exc = ConflictError(str(exc))
    elif isinstance(exc, DjangoValidationError):
        exc = exceptions.ValidationError(exc.message_dict if hasattr(exc, "error_dict") else exc.messages)
    elif isinstance(exc, Http404):
        exc = exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = exceptions.PermissionDenied()

    response = exception_handler(exc, context)
    if response is None:
        return None
    detail = response.data
    code = CODES.get(response.status_code, "error")
    response.data = {
        "error": {
            "code": code,
            "message": _message(detail),
            "details": detail if isinstance(detail, (dict, list)) and response.status_code == 400 else None,
        }
    }
    return response


def error_response(code, message, http_status, details=None):
    return Response({"error": {"code": code, "message": message, "details": details}}, status=http_status)
