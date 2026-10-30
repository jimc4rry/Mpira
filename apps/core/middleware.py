from django.conf import settings
from django.utils import translation


class DefaultToEnglishMiddleware:
    """
    Default first-time visitors to English regardless of browser locale
    (same convention as minitools). Runs before LocaleMiddleware: if no
    language cookie was ever set, hide Accept-Language from it.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.LANGUAGE_COOKIE_NAME not in request.COOKIES:
            request.META.pop("HTTP_ACCEPT_LANGUAGE", None)
        return self.get_response(request)


class UserLanguageMiddleware:
    """A logged-in user's saved language preference wins over the cookie."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and user.language in dict(settings.LANGUAGES):
            translation.activate(user.language)
            request.LANGUAGE_CODE = user.language
        return self.get_response(request)
