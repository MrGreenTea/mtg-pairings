from dal import autocomplete
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.transaction import atomic
from django.http import HttpResponseRedirect
from django.views import generic

from . import forms
from . import models


# Create your views here.

class ListTournaments(LoginRequiredMixin, generic.ListView):
    model = models.Tournament
    template_name = 'tournament_list.html'
    queryset = model.objects.filter(finished=False)

    def get_context_data(self, **kwargs):
        context = super(ListTournaments, self).get_context_data(**kwargs)
        context['finished_tournaments'] = self.model.objects.filter(finished=True)
        return context


class CreateTournament(LoginRequiredMixin, generic.CreateView):
    model = models.Tournament
    template_name = "tournament_form.html"
    form_class = forms.TournamentForm


class ShowTournament(LoginRequiredMixin, generic.DetailView):
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
    def post(self, request, *_, **__):
        self.object = self.get_object()
        form = forms.RoundForm(request.POST, round=self.object.current_round)
        if form.is_valid():
            for player_1_performance, player_2_performance in form.results():
                current_round = self.object.current_round
                duel = current_round.get_duel_for_players(player_1_performance.player,
                                                          player_2_performance.player)
                duel.set_player_performance(player_1_performance)
                duel.set_player_performance(player_2_performance)
            try:
                self.object.start_next_round()
            except AssertionError as error:
                import logging
                logger = logging.getLogger(__name__)
                logger.error('Error when pairing', exc_info=error)
                messages.warning(request, "Couldn't pair for next round. Finished this tournament.")
                self.object.finish()
                return HttpResponseRedirect('#finished')

            return HttpResponseRedirect('#worked')

        return self.render_to_response(
            context=self.get_context_data(round_form=form)
        )


class ListPlayers(LoginRequiredMixin, generic.ListView):
    model = models.Player
    template_name = 'player_list.html'

    def get_queryset(self):
        return self.model.all_time_standing()

    def get_context_data(self, *, object_list=None, **kwargs):
        draw = self.request.GET.get("draw", "false").lower() == "true"
        context = super(ListPlayers, self).get_context_data()
        all_time_ranking = self.model.all_time_ranking(draw=draw)
        context.setdefault(
            "pageranking", all_time_ranking["ranking"]
        )
        context.setdefault(
            "graph", all_time_ranking["graph"].decode("utf8")
        )
        return context


class ShowPlayer(LoginRequiredMixin, generic.DetailView):
    model = models.Player
    template_name = 'player_detail.html'

    def get_context_data(self, **kwargs):
        context = super(ShowPlayer, self).get_context_data(**kwargs)
        context.setdefault(
            "tournaments", {
                tournament: [
                    {"opponent": duel.opponent(self.object), "wins": duel.wins_of(self.object), "losses": duel.losses_of(self.object)}
                    for duel in tournament.duels(self.object)
                             ]
                for tournament in self.object.tournaments.all()
            }
        )
        return context


class ProfilePlayer(ShowPlayer):
    def get_object(self, queryset=None):
        return self.request.user.player


class PlayerAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        # Don't forget to filter out results depending on the visitor !
        if not self.request.user.is_authenticated:
            return models.Player.objects.none()

        qs = models.Player.without_freewin()

        if self.q:
            qs = qs.filter(name__istartswith=self.q)

        return qs
