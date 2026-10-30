from django.apps import AppConfig
from django.db.models.signals import post_save
from django.utils.translation import gettext_lazy as _


def create_space_for_project(sender, instance, created, **kwargs):
    from .models import Space

    if created:
        Space.objects.get_or_create(project=instance, defaults={"name": instance.name})


class WikiConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.wiki"
    verbose_name = _("Wiki")

    def ready(self):
        post_save.connect(
            create_space_for_project, sender="projects.Project", dispatch_uid="wiki_space_for_project"
        )
