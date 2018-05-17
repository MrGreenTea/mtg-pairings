from django.db.transaction import atomic
from django.http import HttpResponseRedirect
from django.views import generic

from . import forms
from . import models


# Create your views here.

class ListTournaments(generic.ListView):
    model = models.Tournament
    template_name = 'tournament_list.html'


class ShowTournament(generic.DetailView):
    model = models.Tournament
    template_name = 'view_tournament.html'
    fields = ['name', 'player', 'rounds']

    object: models.Tournament

    def get_context_data(self, **kwargs):
        context = super(ShowTournament, self).get_context_data(**kwargs)
        current_round = self.object.current_round
        context.setdefault('round_form', forms.RoundForm(round=current_round))
        context['current_round'] = current_round.number
        return context

    @atomic
    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        form = forms.RoundForm(request.POST, round=self.object.current_round)
        if form.is_valid():
            for player_1_performance, player_2_performance in form.results():
                current_round = self.object.current_round
                duel = current_round.get_duel_for_players(player_1_performance.player,
                                                          player_2_performance.player)
                duel.set_player_performance(player_1_performance)
                duel.set_player_performance(player_2_performance)

            self.object.start_next_round()
            return HttpResponseRedirect('#worked')

        return self.render_to_response(
            context=self.get_context_data(round_form=form)
        )
