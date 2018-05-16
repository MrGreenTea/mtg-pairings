from django import forms

from mtg_pairings.models import Round


class RoundForm(forms.Form):
    number = forms.IntegerField(min_value=1, widget=forms.HiddenInput())

    def __init__(self, round: Round, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for i, duel in enumerate(round.duels.all()):
            self.fields[f'duel-{i}-player1'] = forms.IntegerField(min_value=0, label=duel.player_1.name)
            self.fields[f'duel-{i}-player2'] = forms.IntegerField(min_value=0, label=duel.player_2.name)
