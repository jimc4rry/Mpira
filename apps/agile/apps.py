from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AgileConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.agile"
    verbose_name = _("Agile")
