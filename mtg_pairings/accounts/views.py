from django.contrib import auth
from django.contrib.auth.views import LoginView
from django.views import generic

import mtg_pairings.accounts.forms
from mtg_pairings.views import ShowPlayer


class ProfilePlayer(ShowPlayer):
    def get_object(self, queryset=None):
        return self.request.user.player


class RegisterUser(generic.CreateView):
    form_class = mtg_pairings.accounts.forms.RegisterForm
    template_name = "registration/register.html"


    def form_valid(self, form):
        form.save()
        username = form.cleaned_data.get("username")
        raw_password = form.cleaned_data.get("password1")
        user = auth.authenticate(username=username, password=raw_password)
        auth.login(self.request, user)
        return super(RegisterUser, self).form_valid(form)

    def get_success_url(self):
        return self.object.player.get_absolute_url()


class LoginUser(LoginView):
    form_class = mtg_pairings.accounts.forms.LoginForm
