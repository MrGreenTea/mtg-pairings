import crispy_forms.helper
from crispy_forms import layout
from django.contrib.auth.forms import AuthenticationForm
from django import forms
from django.utils.translation import gettext_lazy as _


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = crispy_forms.helper.FormHelper()
        self.helper.add_input(layout.Submit('submit', 'Submit'))


class RegisterForm(LoginForm):
    password_confirm = forms.CharField(
        label=_("Confirm Password"),
        strip=False,
        widget=forms.PasswordInput,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.attrs = {"class": "form-control"}

