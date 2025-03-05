# game/admin.py
from django.contrib import admin
from .models import Country, LiveGame, GameTeam, GameCountryOwnership, SecretWeapon

admin.site.register(Country)
admin.site.register(LiveGame)
admin.site.register(GameTeam)
admin.site.register(GameCountryOwnership)
admin.site.register(SecretWeapon)
