# Generated by Django 4.2.18 on 2025-02-07 06:31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0018_alter_user_country'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='subscription_id',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
