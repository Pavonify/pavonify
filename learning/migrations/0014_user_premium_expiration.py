# Generated by Django 4.2.18 on 2025-02-03 06:46

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0013_student_assignments_completed_student_current_streak_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='premium_expiration',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]
