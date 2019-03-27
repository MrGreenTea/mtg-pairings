from functools import partial

import crispy_forms.helper
from crispy_forms import layout
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = crispy_forms.helper.FormHelper()
        self.helper.add_input(layout.Submit('submit', 'Submit'))


class RegisterForm(UserCreationForm):
    first_name = forms.CharField(max_length=30, required=False)
    last_name = forms.CharField(max_length=30, required=False)
    email = forms.EmailField(max_length=254, help_text='Required. Inform a valid email address.')

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = crispy_forms.helper.FormHelper()
        self.helper.attrs = {"class": "form-control"}
        self.helper = crispy_forms.helper.FormHelper()
        div = partial(layout.Div, css_class="form-group col-md-6")
        self.helper.layout = layout.Layout(
            layout.Row(
                div("username"),
                div("email"),
                css_class="form-row",
            ),
            layout.Row(
                div("first_name"),
                div("last_name"),
                css_class="form-row",
            ),
            layout.Row(
                div("password1"),
                div("password2"),
                css_class="form-row",
            ),
            layout.Submit('submit', 'Submit'),
        )
