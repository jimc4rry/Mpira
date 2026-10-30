from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import Http404


def workspace_admin_required(view):
    """Non-admins get a 404, not a 403 - same convention as the rest of Mpira."""

    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_workspace_admin:
            raise Http404
        return view(request, *args, **kwargs)

    return wrapper
