from django.views import generic

from . import models
from . import forms


# Create your views here.

class ListTournaments(generic.ListView):
    model = models.Tournament
    template_name = 'tournament_list.html'


class ShowTournament(generic.DetailView):
    model = models.Tournament
    template_name = 'view_tournament.html'
    fields = ['name', 'player', 'rounds']

    def get_context_data(self, **kwargs):
        context = super(ShowTournament, self).get_context_data(**kwargs)
        context['round_form'] = forms.RoundForm(round=self.object.current_round)
        return context
