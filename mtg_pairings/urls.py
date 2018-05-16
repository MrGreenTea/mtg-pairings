from django.urls import path

from . import views

urlpatterns = [
    path('', views.ListTournaments.as_view()),
    path('<int:pk>', views.ShowTournament.as_view(), name='tournament_detail')
]
