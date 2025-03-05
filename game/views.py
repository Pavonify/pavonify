# game/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import LiveGame, GameTeam, Country, GameCountryOwnership
from learning.models import VocabularyList  # Adjust the import as needed

@login_required
def host_game(request):
    if request.method == "POST":
        vocabulary_list_id = request.POST.get("vocabulary_list")
        time_limit = int(request.POST.get("time_limit", 10))
        number_of_teams = int(request.POST.get("number_of_teams", 2))
        vocabulary_list = get_object_or_404(VocabularyList, id=vocabulary_list_id)

        # For POST, you need to get the selected class as well.
        class_id = request.POST.get("class_instance")
        class_instance = get_object_or_404(Class, id=class_id)

        game = LiveGame.objects.create(
            teacher=request.user,
            class_instance=class_instance,
            vocabulary_list=vocabulary_list,
            time_limit=time_limit,
            number_of_teams=number_of_teams,
            start_time=timezone.now(),
            end_time=timezone.now() + timezone.timedelta(minutes=time_limit)
        )

        # Create teams for the game.
        team_names = ["Team " + str(i+1) for i in range(number_of_teams)]
        for name in team_names:
            GameTeam.objects.create(live_game=game, team_name=name)

        # Initialize country ownership: set every country to neutral for this game.
        for country in Country.objects.all():
            GameCountryOwnership.objects.create(live_game=game, country=country)
        
        # Redirect to the game lobby page (adjust URL name as needed)
        return redirect("game_lobby", game_id=game.id)

    # On GET, show available vocabulary lists and teacher's classes.
    vocabulary_lists = VocabularyList.objects.filter(teacher=request.user)
    # Using the related name defined on the Class model:
    teacher_classes = request.user.shared_classes.all()
    return render(request, "game/host_game.html", {
        "vocabulary_lists": vocabulary_lists,
        "teacher_classes": teacher_classes,
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
