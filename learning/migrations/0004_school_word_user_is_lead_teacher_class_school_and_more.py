from django.db import migrations, models
import django.db.models.deletion

def create_default_school(apps, schema_editor):
    School = apps.get_model('learning', 'School')
    default_school, created = School.objects.get_or_create(
        name="Default School",
        defaults={
            'location': "Default Location",
            'key': "DEFAULTKEY",
        }
    )
    return default_school.id

class Migration(migrations.Migration):

    dependencies = [
        ('learning', '0003_vocabularylist_classes'),
    ]

    operations = [
        migrations.CreateModel(
            name='School',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('location', models.CharField(blank=True, max_length=255, null=True)),
                ('key', models.CharField(default="DEFAULTKEY", max_length=10, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='Word',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(max_length=255)),
                ('target', models.CharField(max_length=255)),
            ],
        ),
        migrations.AddField(
            model_name='user',
            name='is_lead_teacher',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='class',
            name='school',
            field=models.ForeignKey(
                default=1,  # Temporary default, will be replaced later
                on_delete=django.db.models.deletion.CASCADE,
                to='learning.school',
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='student',
            name='school',
            field=models.ForeignKey(
                default=1,  # Temporary default, will be replaced later
                on_delete=django.db.models.deletion.CASCADE,
                to='learning.school',
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='user',
            name='school',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                to='learning.school',
            ),
        ),
        migrations.RunPython(create_default_school),
    ]
