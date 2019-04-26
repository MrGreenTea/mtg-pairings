import re

import crispy_forms.helper
from crispy_forms import layout
from dal import autocomplete
from django import forms, urls
from django.conf import settings

from mtg_pairings import models

PATTERN = re.compile(r'duel-([0-9]*)-player1')


class PlayerField(forms.ModelMultipleChoiceField):
    def __init__(self, queryset=models.Player.objects, **kwargs):
        super().__init__(queryset, **kwargs)

    widget = autocomplete.ModelSelect2Multiple(url="player-autocomplete")


class RoundForm(forms.Form):
    def __init__(self, *args, round: models.Round, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = crispy_forms.helper.FormHelper()
        self.helper.form_id = 'current-round-form'
        self.helper.form_method = 'post'
        self.helper.form_action = urls.reverse('tournament_detail', kwargs={"pk": round.tournament_id})

        self.helper.add_input(layout.Submit('submit', 'Submit'))
        layout_rows = []
        free_win = None
        for i, duel in enumerate(round.duels.all()):
            player_1, player_2 = f'duel-{i}-player1', f'duel-{i}-player2'

            freewin = models.Player.FREEWIN()
            if freewin in duel.players:
                disabled = True
                free_win = layout.Row(player_1, player_2)
            else:
                disabled = False
                layout_rows.append(layout.Row(player_1, player_2))

            self.fields[player_1] = forms.IntegerField(initial=duel.player_1_wins, min_value=0,
                                                       max_value=settings.MATCH_WINS_NEEDED,
                                                       label=duel.player_1.name,
                                                       disabled=disabled, required=False)
            self.fields[player_2] = forms.IntegerField(initial=duel.player_2_wins, min_value=0,
                                                       max_value=settings.MATCH_WINS_NEEDED,
                                                       label=duel.player_2.name,
                                                       disabled=disabled, required=False)

        if free_win is not None:
            layout_rows.append(free_win)

        self.helper.layout = layout.Layout(
            *layout_rows,
        )

    def clean(self):
        cleaned_data = super().clean().copy()

        for name, value in cleaned_data.items():
            match = PATTERN.match(name)
            if match is not None:
                player_2_id = f'duel-{match.group(1)}-player2'
                if value < settings.MATCH_WINS_NEEDED and cleaned_data[player_2_id] < settings.MATCH_WINS_NEEDED:
                    self.add_error(
                        name, f'Either player needs {settings.MATCH_WINS_NEEDED} wins.'
                    )
                    self.add_error(
                        player_2_id, ""
                    )
                elif value == cleaned_data[player_2_id]:
                    self.add_error(
                        name, f'Only one player can have {settings.MATCH_WINS_NEEDED} wins.'
                    )
                    self.add_error(player_2_id, "")

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


class TournamentForm(forms.ModelForm):
    class Meta:
        model = models.Tournament
        fields = ("name", "players", "teams")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = crispy_forms.helper.FormHelper()
        self.helper.add_layout(crispy_forms.layout.Layout("name", "players"))
        self.helper.add_input(layout.Submit('submit', 'Submit'))

    def clean(self):
        cleaned_data = super().clean()
        teams = cleaned_data.get("teams")
        players = self.cleaned_data.get("players")
        if not teams and players:
            cleaned_data["teams"] = {player.name: [player.name] for player in players}

    def clean_players(self):
        players = self.cleaned_data.get("players")
        if players.count() < 2:
            raise forms.ValidationError("You need at least two players. More players are always more fun ;)")
        if players.count() % 2:
            freewin = models.Player.FREEWIN()
            assert freewin is not None, "Player.FREEWIN not set!"
            if freewin in players:
                raise forms.ValidationError(f"Remove the {freewin} player.")

        return players

    name = forms.CharField(required=True, min_length=2)
    players = PlayerField(required=True)
    teams = forms.CharField(required=False, disabled=True)


class TeamForm(forms.ModelForm):
    team_count = forms.IntegerField(widget=forms.HiddenInput())

    class Meta:
        model = models.Tournament
        exclude = ("name", "players", "finished")

    def __init__(self, *args, **kwargs):
        team_count = kwargs.pop('team_count', 2)

        super().__init__(*args, **kwargs)
        self.fields['team_count'].initial = team_count

        rows = []

        for index in range(int(team_count)):
            # generate extra fields in the number specified via team_count
            name, players = f'team_name_{index}', f'team_players_{index}'
            rows.append(layout.Row(name, players))
            self.fields[name] = forms.CharField(required=False)
            self.fields[players] = PlayerField(required=False)

        self.helper = crispy_forms.helper.FormHelper()
        self.helper.attrs["id"] = "form"

        self.helper.layout = layout.Layout("team_count", *rows)
        self.helper.add_input(layout.Button(name="add-another", value="add another", css_id="add-another"))
        self.helper.add_input(layout.Submit('submit', 'Submit'))

    def clean(self):
        teams = {}
        for index in range(self.cleaned_data["team_count"]):
            name, players = f'team_name_{index}', f'team_players_{index}'
            if self.cleaned_data[players]:
                team_name = self.cleaned_data[name]
                if team_name in teams:
                    self.add_error(name, "Names have to be unique.")
                teams[team_name] = self.cleaned_data[players]

        if not self.errors and len(teams) < 2:
            self.add_error("__all__", "There need to be at least 2 teams!")
        self.cleaned_data["teams"] = teams
