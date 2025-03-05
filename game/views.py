# game/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import LiveGame, GameTeam, Country, GameCountryOwnership, SecretWeapon
from learning.models import VocabularyList, Class  # Adjust if your app name is different

@login_required
def host_game(request):
    # Get the teacher's classes and vocabulary lists.
    teacher_classes = Class.objects.filter(teachers=request.user)
    vocabulary_lists = VocabularyList.objects.filter(teacher=request.user)
    
    if request.method == "POST":
        # Retrieve form values.
        class_id = request.POST.get("class_instance")
        vocabulary_list_id = request.POST.get("vocabulary_list")
        time_limit = int(request.POST.get("time_limit", 10))
        number_of_teams = int(request.POST.get("number_of_teams", 2))
        
        class_instance = get_object_or_404(Class, id=class_id)
        vocabulary_list = get_object_or_404(VocabularyList, id=vocabulary_list_id)
        
        # Create the LiveGame instance.
        game = LiveGame.objects.create(
            teacher=request.user,
            class_instance=class_instance,
            vocabulary_list=vocabulary_list,
            time_limit=time_limit,
            number_of_teams=number_of_teams,
            start_time=timezone.now(),
            end_time=timezone.now() + timezone.timedelta(minutes=time_limit)
        )
        
        # Create teams (e.g., "Team 1", "Team 2", etc.).
        team_names = ["Team " + str(i + 1) for i in range(number_of_teams)]
        for name in team_names:
            GameTeam.objects.create(live_game=game, team_name=name)
        
        # Initialize country ownership: set every country to neutral.
        for country in Country.objects.all():
            GameCountryOwnership.objects.create(live_game=game, country=country)
        
        # Redirect to the game lobby.
        return redirect("game_lobby", game_id=game.id)
    
    return render(request, "game/host_game.html", {
        "teacher_classes": teacher_classes,
        "vocabulary_lists": vocabulary_lists,
    })

@login_required
def game_lobby(request, game_id):
    game = get_object_or_404(LiveGame, id=game_id)
    teams = game.teams.all()
    ownerships = game.country_ownership.select_related("country", "controlled_by")
    secret_weapons = game.secret_weapons.all()
    context = {
        "game": game,
        "teams": teams,
        "ownerships": ownerships,
        "secret_weapons": secret_weapons,
    }
    return render(request, "game/game_lobby.html", context)
