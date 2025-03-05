# Generated by Django 4.2.18 on 2025-03-05 05:42

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('learning', '0025_alter_user_ai_credits'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Country',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True)),
                ('population', models.PositiveIntegerField()),
                ('strength', models.PositiveIntegerField(help_text='Number of vocabulary words required for conquest')),
                ('neighbors', models.ManyToManyField(blank=True, to='game.country')),
            ],
        ),
        migrations.CreateModel(
            name='GameTeam',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('team_name', models.CharField(max_length=50)),
                ('team_color', models.CharField(blank=True, max_length=20, null=True)),
                ('score', models.IntegerField(default=0)),
            ],
        ),
        migrations.CreateModel(
            name='LiveGame',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_time', models.DateTimeField(default=django.utils.timezone.now)),
                ('end_time', models.DateTimeField(blank=True, null=True)),
                ('time_limit', models.PositiveIntegerField(help_text='Game duration in minutes')),
                ('number_of_teams', models.PositiveSmallIntegerField(default=2, help_text='Number of teams (e.g., 2, 3, or 4)')),
                ('is_active', models.BooleanField(default=True)),
                ('teacher', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='hosted_games', to=settings.AUTH_USER_MODEL)),
                ('vocabulary_list', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='learning.vocabularylist')),
            ],
        ),
        migrations.CreateModel(
            name='SecretWeapon',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('weapon_type', models.CharField(choices=[('diplomatic', 'Diplomatic Leverage'), ('economic', 'Economic Boom'), ('spy', 'Spy Network'), ('rapid', 'Rapid Deployment'), ('paratroopers', 'Paratroopers'), ('sabotage', 'Sabotage')], max_length=20)),
                ('last_activated', models.DateTimeField(blank=True, null=True)),
                ('country', models.ForeignKey(help_text='The neutral country where this weapon is hidden', on_delete=django.db.models.deletion.CASCADE, to='game.country')),
                ('held_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='secret_weapons', to='game.gameteam')),
                ('live_game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='secret_weapons', to='game.livegame')),
            ],
        ),
        migrations.AddField(
            model_name='gameteam',
            name='live_game',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='teams', to='game.livegame'),
        ),
        migrations.CreateModel(
            name='GameCountryOwnership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('reinforcement_level', models.PositiveIntegerField(default=0)),
                ('controlled_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='countries', to='game.gameteam')),
                ('country', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='game.country')),
                ('live_game', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='country_ownership', to='game.livegame')),
            ],
            options={
                'unique_together': {('live_game', 'country')},
            },
        ),
    ]
