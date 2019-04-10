import logging

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class MtgPairingsConfig(AppConfig):
    name = 'mtg_pairings'
    DEFAULT_GROUP_NAME = "Player"
    DEFAULT_GROUP_PERMISSIONS = ["add_player", "add_tournament"]
    DEFAULT_GROUP = None

    def ready(self):
        post_migrate.connect(create_player_group, sender=self)


def create_player_group(apps, app_config: MtgPairingsConfig, verbosity, *args, **kwargs):
    Permission = apps.get_model("auth", "Permission")
    Group = apps.get_model("auth", "Group")

    permissions = Permission.objects.filter(codename__in=app_config.DEFAULT_GROUP_PERMISSIONS)
    assert len(permissions) == len(app_config.DEFAULT_GROUP_PERMISSIONS)
    player_group, created = Group.objects.get_or_create(name=app_config.DEFAULT_GROUP_NAME)
    player_group.permissions.set(permissions)

    if created and verbosity:
        logging.getLogger(__name__).info("Created %s group", player_group.name)
