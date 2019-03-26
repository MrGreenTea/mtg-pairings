from django.apps import AppConfig
from django.db import models


class MtgPairingsConfig(AppConfig):
    name = 'mtg_pairings'

    def __init__(self, app_name, app_module):
        models.signals.class_prepared.connect(
            receiver=self.init_freewin_player
        )
        super().__init__(app_name, app_module)

    @staticmethod
    def init_freewin_player(sender, **kwargs):
        if hasattr(sender, "FREEWIN"):
            sender.FREEWIN, created = sender.objects.get_or_create(name="FREE WIN")
            print(sender, "FREEWIN created:", created)
