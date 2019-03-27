import django.contrib.auth.urls
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views


urlpatterns = [
    path('login/', views.LoginUser.as_view(), name="login"),
    path('logout/', auth_views.LogoutView.as_view(), name="logout"),

    path('profile/', views.ProfilePlayer.as_view(), name="profile"),
    path('register/', views.RegisterUser.as_view(), name="register"),
]

EXCLUDED = {p.name for p in urlpatterns}
urlpatterns += [p for p in django.contrib.auth.urls.urlpatterns if p.name not in EXCLUDED]
