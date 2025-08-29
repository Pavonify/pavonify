from django.db import models
from django.contrib.auth.models import AbstractUser
import uuid
import random
import string
from django.utils.timezone import now
from datetime import datetime, timedelta
from django_countries.fields import CountryField

def generate_school_key():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

class School(models.Model):
    name = models.CharField(max_length=255)
    location = models.CharField(max_length=255, blank=True, null=True)
    key = models.CharField(max_length=10, unique=True, default=generate_school_key)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

from django.utils.timezone import now
from datetime import timedelta
from django.contrib.auth.models import AbstractUser
from django.db import models
from django_countries.fields import CountryField


class User(AbstractUser):
    is_student = models.BooleanField(default=False)
    is_teacher = models.BooleanField(default=False)
    is_lead_teacher = models.BooleanField(default=False)
    school = models.ForeignKey("School", on_delete=models.SET_NULL, null=True, blank=True)

    first_name = models.CharField(max_length=50, blank=False)
    last_name = models.CharField(max_length=50, blank=False)
    email = models.EmailField(unique=True)
    country = CountryField(blank_label="Select a country")

    # Default premium_expiration to now (expired by default)
    premium_expiration = models.DateTimeField(default=now)

    # Stripe subscription fields
    subscription_id = models.CharField(max_length=255, blank=True, null=True)
    subscription_cancelled = models.BooleanField(default=False)

    # Pavonicoins for AI requests (1 on signup, 5 on subscription)
    ai_credits = models.IntegerField(default=1)  # Grant 1 credit on registration

    @property
    def is_premium(self):
        """Check if premium subscription is active."""
        return self.premium_expiration > now()

    def upgrade_to_premium(self, days=30):
        """Extend premium expiration by given days."""
        current_expiration = self.premium_expiration if self.premium_expiration > now() else now()
        self.premium_expiration = current_expiration + timedelta(days=days)
        self.add_credits(5)  # Grant 5 Pavonicoins on upgrade
        self.save()

    def deduct_credit(self):
        """Deduct 1 AI credit if available."""
        if self.ai_credits > 0:
            self.ai_credits -= 1
            self.save()
            return True
        return False  # Not enough credits

    def add_credits(self, amount):
        """Add Pavonicoins."""
        self.ai_credits += amount
        self.save()

    def __str__(self):
        return self.username


class Class(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    language = models.CharField(max_length=50)
    teachers = models.ManyToManyField(User, related_name="shared_classes")
    icon = models.ImageField(upload_to="class_icons/", blank=True, null=True)
    vocabulary_lists = models.ManyToManyField("VocabularyList", related_name="linked_classes", blank=True)

    def __str__(self):
        return self.name

class Student(models.Model):
    school = models.ForeignKey(School, on_delete=models.CASCADE)
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    year_group = models.IntegerField()
    date_of_birth = models.DateField()
    username = models.CharField(max_length=50, unique=True)
    password = models.CharField(max_length=50)
    classes = models.ManyToManyField(Class, related_name="students")
    last_login = models.DateTimeField(null=True, blank=True)
    
    # Existing points tracking
    total_points = models.PositiveIntegerField(default=0)
    weekly_points = models.PositiveIntegerField(default=0)
    monthly_points = models.PositiveIntegerField(default=0)

    # 🛠️ New fields for tracking achievements
    last_activity = models.DateField(null=True, blank=True)  # Last day they practiced
    current_streak = models.PositiveIntegerField(default=0)  # How many days in a row
    highest_streak = models.PositiveIntegerField(default=0)  # Their best-ever streak
    assignments_completed = models.PositiveIntegerField(default=0)  # Number of completed assignments

    flashcard_games_played = models.PositiveIntegerField(default=0)
    match_up_games_played = models.PositiveIntegerField(default=0)
    destroy_wall_games_played = models.PositiveIntegerField(default=0)

    def update_streak(self):
        """ Updates the streak based on last activity """
        today = now().date()
        if self.last_activity == today - timedelta(days=1):  # Streak continues
            self.current_streak += 1
        elif self.last_activity != today:  # Streak broken
            self.current_streak = 1
        self.last_activity = today
        if self.current_streak > self.highest_streak:
            self.highest_streak = self.current_streak
        self.save()

class VocabularyList(models.Model):
    name = models.CharField(max_length=100)
    source_language = models.CharField(max_length=50)
    target_language = models.CharField(max_length=50)
    teacher = models.ForeignKey(User, on_delete=models.CASCADE)
    classes = models.ManyToManyField(Class, related_name="linked_vocab_lists", blank=True)

    def __str__(self):
        return f"{self.name} ({self.source_language} → {self.target_language})"

class VocabularyWord(models.Model):
    word = models.CharField(max_length=100)
    translation = models.CharField(max_length=100)
    list = models.ForeignKey("VocabularyList", on_delete=models.CASCADE, related_name="words")

    def __str__(self):
        return f"{self.word} → {self.translation}"



class Progress(models.Model):
    student = models.ForeignKey(User, on_delete=models.CASCADE, limit_choices_to={'is_student': True})
    word = models.ForeignKey(VocabularyWord, on_delete=models.CASCADE)
    correct_attempts = models.IntegerField(default=0)
    incorrect_attempts = models.IntegerField(default=0)
    next_due = models.DateTimeField(null=True, blank=True)
    review_interval = models.IntegerField(default=1)
    last_seen = models.DateTimeField(null=True, blank=True)
    review_count = models.PositiveIntegerField(default=0)
    points = models.IntegerField(default=0)  # Points for this specific word interaction

    def update_points(self, points_awarded):
        self.points += points_awarded
        self.save()

class Word(models.Model):
    source = models.CharField(max_length=255)
    target = models.CharField(max_length=255)

class Assignment(models.Model):
    name = models.CharField(max_length=255)
    class_assigned = models.ForeignKey(Class, on_delete=models.CASCADE)
    vocab_list = models.ForeignKey(VocabularyList, on_delete=models.CASCADE)
    deadline = models.DateTimeField()
    target_points = models.IntegerField()  # Total target points for the assignment

    # Existing Modes
    include_flashcards = models.BooleanField(default=False)
    points_per_flashcard = models.IntegerField(default=1)

    include_matchup = models.BooleanField(default=False)
    points_per_matchup = models.IntegerField(default=1)

    include_fill_gap = models.BooleanField(default=False)
    points_per_fill_gap = models.IntegerField(default=1)

    include_destroy_wall = models.BooleanField(default=False)
    points_per_destroy_wall = models.IntegerField(default=1)

    include_unscramble = models.BooleanField(default=False)
    points_per_unscramble = models.IntegerField(default=1)

    # ✅ NEW MODES ✅
    include_listening_dictation = models.BooleanField(default=False)
    points_per_listening_dictation = models.IntegerField(default=1)

    include_listening_translation = models.BooleanField(default=False)
    points_per_listening_translation = models.IntegerField(default=1)

    teacher = models.ForeignKey(User, on_delete=models.CASCADE, limit_choices_to={'is_teacher': True})

    def __str__(self):
        return self.name


class AssignmentProgress(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE)
    points_earned = models.IntegerField(default=0)
    time_spent = models.DurationField(default=timedelta())

    def __str__(self):
        return f"{self.student.username} - {self.assignment.name}"

    def update_progress(self, points, time_spent):
        self.points_earned += points

        # Ensure `time_spent` is always a timedelta
        if isinstance(time_spent, int):  # If somehow an int is passed, convert it
            time_spent = timedelta(seconds=time_spent)

        self.time_spent += time_spent
        self.completed = self.points_earned >= self.assignment.target_points
        self.save()

class Trophy(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)  # Trophy Name
    description = models.TextField()  # Brief explanation
    icon = models.ImageField(upload_to="trophies/", blank=True, null=True)  # Trophy icon (optional)
    points_required = models.IntegerField(null=True, blank=True)  # Points required (if applicable)
    streak_required = models.IntegerField(null=True, blank=True)  # Streak required (if applicable)
    assignment_count_required = models.IntegerField(null=True, blank=True)  # Assignments required
    game_type = models.CharField(max_length=50, blank=True, null=True)  # If for a specific game
    is_hidden = models.BooleanField(default=False)  # If the trophy is secret
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class StudentTrophy(models.Model):
    student = models.ForeignKey("Student", on_delete=models.CASCADE, related_name="trophies")
    trophy = models.ForeignKey("Trophy", on_delete=models.CASCADE, related_name="awarded_to")
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("student", "trophy")  # Prevent duplicate trophies

    def __str__(self):
        return f"{self.student.first_name} earned {self.trophy.name}"

class Announcement(models.Model):
    """ Stores teacher dashboard announcements """
    title = models.CharField(max_length=200)
    text_body = models.TextField()
    image = models.ImageField(upload_to='announcements/', blank=True, null=True)
    created_at = models.DateTimeField(default=now)

    class Meta:
        ordering = ['-created_at']  # Show newest posts first

    def __str__(self):
        return self.title

# NEW MODEL: Stores the generated AI texts
class ReadingLabText(models.Model):
    teacher = models.ForeignKey(User, on_delete=models.CASCADE)
    vocabulary_list = models.ForeignKey(VocabularyList, on_delete=models.SET_NULL, null=True)
    selected_words = models.ManyToManyField(VocabularyWord, related_name="included_in_reading_lab")  # ✅ Stores selected words
    exam_board = models.CharField(max_length=100)
    topic = models.CharField(max_length=100)
    level = models.CharField(max_length=10, choices=[
        ("A1", "A1"), ("A2", "A2"), ("B1", "B1"), ("B2", "B2"), ("C1", "C1"), ("C2", "C2")
    ])
    word_count = models.PositiveIntegerField()

    # ✅ Automatically taken from VocabularyList
    source_language = models.CharField(max_length=50)
    target_language = models.CharField(max_length=50)

    # ✅ AI-Generated texts stored
    generated_text_source = models.TextField()
    generated_text_target = models.TextField()
    
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        """ Ensure source & target language are set correctly. """
        if self.vocabulary_list:
            self.source_language = self.vocabulary_list.source_language
            self.target_language = self.vocabulary_list.target_language
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.teacher.username} - {self.topic} ({self.created_at.date()})"

class AssignmentAttempt(models.Model):
    MODE_CHOICES = [
        ('flashcards', 'Flashcards'),
        ('matchup', 'Matchup'),
        ('fill_gap', 'Gap Fill'),	
        ('destroy_wall', 'Destroy the Wall'),
        ('unscramble', 'Unscramble'),
        ('listening_dictation', 'Listening Dictation'),
        ('listening_translation', 'Listening Translation'),
    ]
    
    student = models.ForeignKey(Student, on_delete=models.CASCADE)
    assignment = models.ForeignKey(Assignment, on_delete=models.CASCADE)
    vocabulary_word = models.ForeignKey(VocabularyWord, on_delete=models.CASCADE)
    mode = models.CharField(max_length=30, choices=MODE_CHOICES)
    is_correct = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        status = "Correct" if self.is_correct else "Incorrect"
        return f"{self.student.username} - {self.vocabulary_word.word} ({self.mode}): {status} at {self.timestamp}"


class GrammarLadder(models.Model):
    teacher = models.ForeignKey(User, on_delete=models.CASCADE, related_name="grammar_ladders")
    name = models.CharField(max_length=100)
    prompt = models.TextField()
    language = models.CharField(max_length=20, choices=[
        ('French', 'French'),
        ('German', 'German'),
        ('Spanish', 'Spanish'),
        ('Italian', 'Italian'),
    ])
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.teacher.username} - {self.name} ({self.language})"


class LadderItem(models.Model):
    ladder = models.ForeignKey(GrammarLadder, on_delete=models.CASCADE, related_name="items")
    phrase = models.CharField(max_length=255)
    is_correct = models.BooleanField()

    def __str__(self):
        return f"{self.phrase} - {'Correct' if self.is_correct else 'Incorrect'}"


