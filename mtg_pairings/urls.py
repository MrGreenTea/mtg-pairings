from django.urls import path

from . import views
urlpatterns = [
    path('', views.ListTournaments.as_view(), name='tournament_list'),
    path('players/', views.ListPlayers.as_view(), name='player_list'),
    path('players/<str:pk>', views.ShowPlayer.as_view(), name='player_detail'),
    path('<int:pk>', views.ShowTournament.as_view(), name='tournament_detail')
]

