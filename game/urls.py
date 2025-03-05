# game/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('host/', views.host_game, name='host_game'),
    path('lobby/<int:game_id>/', views.game_lobby, name='game_lobby'),
]
