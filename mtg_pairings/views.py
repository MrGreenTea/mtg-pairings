from dal import autocomplete
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.transaction import atomic
from django.http import HttpResponseRedirect
from django.views import generic

from sentry_sdk import configure_scope

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


class CreateTournament(PermissionRequiredMixin, generic.CreateView):
    permission_required = 'mtg_pairings.add_tournament'
    model = models.Tournament
    template_name = "base_form.html"
    form_class = forms.TournamentForm


class ShowTournament(LoginRequiredMixin, generic.DetailView):
    model = models.Tournament
    template_name = 'view_tournament.html'
    fields = ('name', 'player', 'rounds')

    object: models.Tournament

    def get_context_data(self, **kwargs):
        with configure_scope() as scope:
            scope.user = self.request.user
            context = super(ShowTournament, self).get_context_data(**kwargs)
            current_round = self.object.current_round
            context.setdefault('round_form', forms.RoundForm(round=current_round))
            context['current_round'] = current_round.number
            return context

    @atomic
    def post(self, request, *_, **__):
        with configure_scope() as scope:
            scope.user = {
                "username": self.request.user.username,
                "email": self.request.user.email,
            }

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
                    messages.warning(request, "Couldn't pair all players for next round. Finished this tournament.")
                    self.object.finish()
                    return HttpResponseRedirect('#finished')

                return HttpResponseRedirect('#worked')

            return self.render_to_response(
                context=self.get_context_data(round_form=form)
            )


class CreateTeams(LoginRequiredMixin, generic.UpdateView):
    model = models.Tournament
    template_name = "team_form.html"
    form_class = forms.TeamForm

    object: models.Tournament

    def form_valid(self, form):
        self.object.teams = form.cleaned_data["teams"]
        return HttpResponseRedirect(self.object.get_absolute_url())


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
                    {"opponent": duel.opponent(self.object), "wins": duel.wins_of(self.object),
                     "losses": duel.losses_of(self.object)}
                    for duel in tournament.duels(self.object)
                ]
                for tournament in self.object.tournaments.all()
            }
        )
        return context


class PlayerAutocomplete(autocomplete.Select2QuerySetView):
    def get_queryset(self):
        if not self.request.user.is_authenticated:
            return models.Player.objects.none()

        qs = models.Player.without_freewin()

        query = self.q.strip()
        if query:
            qs = qs.filter(name__istartswith=query)

        return qs
