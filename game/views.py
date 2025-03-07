# game/views.py
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.utils.timezone import now
from django.http import JsonResponse
from .models import LiveGame, GameTeam, Country, GameCountryOwnership, SecretWeapon
from django.urls import reverse
import traceback
import random
from django.views.decorators.csrf import csrf_exempt
import json

from django.contrib.auth import get_user_model

User = get_user_model()

from learning.models import VocabularyList, Class, User, VocabularyWord  # Adjust the import as needed

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

    if request.user == game.teacher:
        is_teacher = True
    else:
        is_teacher = False
        # Ensure students can only join if they belong to the class assigned
        if not request.user.is_student or game.class_instance not in request.user.shared_classes.all():
            return redirect("dashboard")  # Redirect students if they're not in this class

    # Get all teams & students assigned to this game
    teams = GameTeam.objects.filter(live_game=game)
    students_in_game = User.objects.filter(is_student=True, shared_classes=game.class_instance)

    # If teams are empty, assign students evenly
    if teams.count() == 0:
        team_names = ["Red", "Blue", "Green", "Yellow"][:game.number_of_teams]
        for name in team_names:
            GameTeam.objects.create(live_game=game, team_name=name)

    # Assign students to teams if they haven't been assigned yet
    for student in students_in_game:
        if not GameTeam.objects.filter(members=student, live_game=game).exists():
            available_teams = GameTeam.objects.filter(live_game=game).order_by("members__count")
            available_teams.first().members.add(student)

    return render(request, "game/lobby.html", {
        "game": game,
        "teams": teams,
        "students": students_in_game,
        "is_teacher": is_teacher,
    })


def start_game(request, game_id):
    game = get_object_or_404(LiveGame, id=game_id)

    if game.is_active:
        return JsonResponse({"error": "Game has already started!"}, status=400)

    game.is_active = True
    game.save()

    teams = list(game.teams.all())
    countries = list(Country.objects.all())

    # ✅ Ensure no duplicate country assignment
    assigned_countries = set(GameCountryOwnership.objects.filter(live_game=game).values_list("country_id", flat=True))

    # 1️⃣ SHUFFLE COUNTRIES TO RANDOMIZE SELECTION
    random.shuffle(countries)

    # 2️⃣ ASSIGN ONE COUNTRY PER TEAM (ensuring distance)
    for team in teams:
        for country in countries:
            if country.id not in assigned_countries:
                GameCountryOwnership.objects.create(live_game=game, country=country, controlled_by=team)
                assigned_countries.add(country.id)  # ✅ Mark country as assigned
                break  # ✅ Move to next team

    # 3️⃣ ASSIGN SECRET WEAPONS TO RANDOM NEUTRAL COUNTRIES
    secret_weapon_types = ["diplomatic", "economic", "spy", "rapid", "paratroopers", "sabotage"]
    
    neutral_countries = [c for c in countries if c.id not in assigned_countries]
    random.shuffle(neutral_countries)

    for i, country in enumerate(neutral_countries[:len(secret_weapon_types)]):
        SecretWeapon.objects.create(
            live_game=game,
            country=country,
            weapon_type=secret_weapon_types[i]
        )


def game_play(request, game_id):
    game = get_object_or_404(LiveGame, id=game_id)
    return render(request, "game/game_play.html", {"game": game})

def game_overview(request, game_id):
    print(f"✅ LOADING GAME OVERVIEW for {request.user.username}")  # Debug confirmation
    game = get_object_or_404(LiveGame, id=game_id)
    teams = game.teams.all()  # Fetch all teams in the game
    country_ownership = game.country_ownership.all()  # Fetch country ownership details

    # 🚀 Confirm it's loading the correct template
    response = render(request, "game/game_overview.html", {
        "game": game,
        "teams": teams,
        "country_ownership": country_ownership
    })
    print(f"✅ game_overview is being served to {request.user.username}")
    return response


def get_time_left(request, game_id):
    """Returns the remaining time in seconds for the game."""
    game = get_object_or_404(LiveGame, id=game_id)
    
    if not game.is_active:
        return JsonResponse({"error": "Game has ended"}, status=400)
    
    remaining_time = (game.end_time - now()).total_seconds()
    return JsonResponse({"time_left": max(0, int(remaining_time))})


def get_countries(request, game_id):
    game = get_object_or_404(LiveGame, id=game_id)
    
    countries = []
    for ownership in game.country_ownership.all():
        countries.append({
            "id": ownership.country.id,
            "name": ownership.country.name,
            "strength": ownership.country.strength,
            "team_color": ownership.controlled_by.team_color if ownership.controlled_by else "gray",
            "is_adjacent": ownership.country in get_adjacent_countries(game, request.user),
        })
    
    return JsonResponse({"countries": countries})


@csrf_exempt
def attack_country(request, game_id):
    game = get_object_or_404(LiveGame, id=game_id)
    data = json.loads(request.body)
    country = get_object_or_404(Country, id=data["country_id"])
    answer = data["answer"]

    # ✅ Get random word from game’s vocabulary list
    vocab_word = VocabularyWord.objects.filter(list=game.vocabulary_list).order_by("?").first()

    # ✅ Check if answer is correct
    if vocab_word and vocab_word.translation.lower() == answer.lower():
        country_ownership = GameCountryOwnership.objects.get(live_game=game, country=country)
        country_ownership.controlled_by = get_user_team(game, request.user)
        country_ownership.save()

        return JsonResponse({"success": True, "message": "Country conquered!"})

    return JsonResponse({"success": False, "message": "Incorrect answer!"})

def get_game_updates(request, game_id):
    # Dummy data for now, replace with real game logs
    updates = ["Team Red conquered France!", "Team Blue is attacking Germany!"]
    return JsonResponse({"updates": updates})