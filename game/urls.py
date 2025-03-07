# game/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Hosting & Lobby
    path('host/', views.host_game, name='host_game'),
    path('lobby/<int:game_id>/', views.game_lobby, name='game_lobby'),

    # Game Start & Play
    path('start/<int:game_id>/', views.start_game, name='start_game'),
    path('play/<int:game_id>/', views.game_play, name='game_play'),
    path('overview/<int:game_id>/', views.game_overview, name='game_overview'),

    # API Endpoints (for live updates)
    path('get_time_left/<int:game_id>/', views.get_time_left, name='get_time_left'),

    path('get_countries/<int:game_id>/', views.get_countries, name='get_countries'),
    path('attack_country/<int:game_id>/', views.attack_country, name='attack_country'),
    path('get_game_updates/<int:game_id>/', views.get_game_updates, name='get_game_updates'),
]