# game/models.py
from django.db import models
from django.conf import settings
from django.utils import timezone

User = settings.AUTH_USER_MODEL

# --- Country Data (Static Map Data) ---
class Country(models.Model):
    name = models.CharField(max_length=100, unique=True)
    population = models.PositiveIntegerField()
    # "Strength" represents the number of vocabulary words required to conquer
    strength = models.PositiveIntegerField(help_text="Number of vocabulary words required for conquest")
    # Many-to-many relationship to represent neighboring countries
    neighbors = models.ManyToManyField('self', symmetrical=True, blank=True)

    def __str__(self):
        return self.name

# --- Live Game Session ---
class LiveGame(models.Model):
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name="hosted_games")
    # New: The specific class hosting this game (assumes your teacher class model is in the 'learning' app)
    class_instance = models.ForeignKey("learning.Class", on_delete=models.CASCADE, default="3208fe35-ce64-4343-9f7a-4e3d6b46514f")
    vocabulary_list = models.ForeignKey('learning.VocabularyList', on_delete=models.CASCADE)
    start_time = models.DateTimeField(default=timezone.now)
    end_time = models.DateTimeField(null=True, blank=True)
    time_limit = models.PositiveIntegerField(help_text="Game duration in minutes")
    number_of_teams = models.PositiveSmallIntegerField(default=2, help_text="Number of teams (e.g., 2, 3, or 4)")
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Game {self.id} hosted by {self.teacher}"

class GameTeam(models.Model):
    live_game = models.ForeignKey(LiveGame, on_delete=models.CASCADE, related_name="teams")
    team_name = models.CharField(max_length=50)
    team_color = models.CharField(max_length=20, blank=True, null=True)  # e.g., "red", "blue", etc.
    score = models.IntegerField(default=0)
    # Reference the User model (which includes both teachers and students).
    # In practice, only users with is_student=True should be added.
    members = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="game_teams", blank=True)

    def __str__(self):
        return f"{self.team_name} (Game {self.live_game.id})"


# --- Country Ownership in a Game ---
class GameCountryOwnership(models.Model):
    live_game = models.ForeignKey(LiveGame, on_delete=models.CASCADE, related_name="country_ownership")
    country = models.ForeignKey(Country, on_delete=models.CASCADE)
    # controlled_by is null if the country is neutral
    controlled_by = models.ForeignKey(GameTeam, on_delete=models.SET_NULL, null=True, blank=True, related_name="countries")
    reinforcement_level = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('live_game', 'country')

    def __str__(self):
        team = self.controlled_by.team_name if self.controlled_by else "Neutral"
        return f"{self.country.name} (Game {self.live_game.id}) - {team}"

# --- Secret Weapons ---
SECRET_WEAPON_CHOICES = [
    ('diplomatic', 'Diplomatic Leverage'),
    ('economic', 'Economic Boom'),
    ('spy', 'Spy Network'),
    ('rapid', 'Rapid Deployment'),
    ('paratroopers', 'Paratroopers'),
    ('sabotage', 'Sabotage'),
]

class SecretWeapon(models.Model):
    live_game = models.ForeignKey(LiveGame, on_delete=models.CASCADE, related_name="secret_weapons")
    country = models.ForeignKey(Country, on_delete=models.CASCADE, help_text="The neutral country where this weapon is hidden")
    weapon_type = models.CharField(max_length=20, choices=SECRET_WEAPON_CHOICES)
    held_by = models.ForeignKey(GameTeam, on_delete=models.SET_NULL, null=True, blank=True, related_name="secret_weapons")
    last_activated = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.get_weapon_type_display()} in {self.country.name} (Game {self.live_game.id})"
