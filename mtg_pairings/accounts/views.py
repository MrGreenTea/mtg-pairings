from django.contrib.auth.views import LoginView
from django.views import generic

import mtg_pairings.accounts.forms
from mtg_pairings.views import ShowPlayer


class ProfilePlayer(ShowPlayer):
    def get_object(self, queryset=None):
        return self.request.user.player


class RegisterUser(generic.FormView):
    form_class = mtg_pairings.accounts.forms.RegisterForm
    template_name = "registration/register.html"

    def post(self, request, *args, **kwargs):
        pass


class LoginUser(LoginView):
    form_class = mtg_pairings.accounts.forms.LoginForm
