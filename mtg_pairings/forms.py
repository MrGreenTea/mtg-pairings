import re

import crispy_forms.helper
from crispy_forms import layout
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError

from mtg_pairings import models

PATTERN = re.compile(r'duel-([0-9]*)-player1')


class RoundForm(forms.Form):
    def __init__(self, *args, round: models.Round, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = crispy_forms.helper.FormHelper()
        self.helper.form_id = 'current-round-form'
        self.helper.form_method = 'post'
        self.helper.form_action = 'submit_round'

        self.helper.add_input(layout.Submit('submit', 'Submit'))
        layout_rows = []
        for i, duel in enumerate(round.duels.all()):
            player_1, player_2 = f'duel-{i}-player1', f'duel-{i}-player2'

            layout_rows.append(layout.Row(player_1, player_2))

            self.fields[player_1] = forms.IntegerField(initial=duel.player_1_wins, min_value=0,
                                                       max_value=settings.MATCH_WINS_NEEDED,
                                                       label=duel.player_1.name)
            self.fields[player_2] = forms.IntegerField(initial=duel.player_2_wins, min_value=0,
                                                       max_value=settings.MATCH_WINS_NEEDED,
                                                       label=duel.player_2.name)

        self.helper.layout = layout.Layout(
            *layout_rows
        )

    def clean(self):
        cleaned_data = super().clean()

        for name, value in cleaned_data.items():

            match = PATTERN.match(name)
            if match:
                player_2_id = f'duel-{match.group(1)}-player2'
                if value < settings.MATCH_WINS_NEEDED and cleaned_data[player_2_id] < settings.MATCH_WINS_NEEDED:
                    raise ValidationError(f'Either player needs {settings.MATCH_WINS_NEEDED} wins.')
                if value == cleaned_data[player_2_id]:
                    raise ValidationError(f'Only one player can have {settings.MATCH_WINS_NEEDED} wins.')

        return cleaned_data

    def results(self):
        for name, value in self.cleaned_data.items():
            match = PATTERN.match(name)
            if match:
                player_1 = models.Player.objects.get(name=self.fields[name].label)
                player_2_id = f'duel-{match.group(1)}-player2'
                player_2 = models.Player.objects.get(name=self.fields[player_2_id].label)
                player_2_result = self.cleaned_data[player_2_id]
                yield (models.Performance(player_1, wins=value, losses=player_2_result, match_wins=0, match_losses=0),
                       models.Performance(player_2, wins=player_2_result, losses=value, match_wins=0, match_losses=0))
