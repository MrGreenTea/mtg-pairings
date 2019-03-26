from django.urls import path

from . import views

urlpatterns = [
    path('', views.ListTournaments.as_view(), name='tournament_list'),
    path('start', views.CreateTournament.as_view(), name='create_tournament'),
    path('players/', views.ListPlayers.as_view(), name='player_list'),
    path('players/autocomplete', views.PlayerAutocomplete.as_view(create_field='name'), name="player-autocomplete"),
    path('players/<str:pk>', views.ShowPlayer.as_view(), name='player_detail'),
    path('<int:pk>', views.ShowTournament.as_view(), name='tournament_detail'),

]

