from django.core.management.base import BaseCommand
from django.utils.text import slugify
from achievements.models import Trophy


TROPHY_NAMES = [
    "First Steps",
    "Consistency is Key",
    "Streak Master",
    "Weekend Warrior",
    "Daily Scholar",
    "Perfect Attendance",
    "Marathon Session",
    "Early Bird",
    "Night Owl",
    "Double Agent",
    "Homework Hero",
    "Clean Sweep",
    "Speedy Submitter",
    "Last Minute Legend",
    "Quality Over Quantity",
    "Assignment Veteran",
    "Pavonify Graduate",
    "Retry Champion",
    "All-Rounder",
    "Consistent Climber",
    "First 100%",
    "Gold Standard",
    "Silver Standard",
    "Bronze Standard",
    "Personal Best",
    "High Flyer",
    "Subject Specialist",
    "Across the Board",
    "Bounce Back",
    "Pavonicoin Millionaire",
    "Dawn Devotee",
    "Lunchtime Learner",
    "Midnight Maverick",
    "Fast Finisher",
    "Steady Worker",
    "Double Time",
    "Hat-Trick",
    "Pavonify Marathon",
    "Consistent Pace",
    "Lightning Bolt",
    "Weekly Winner",
    "Top 5 Finisher",
    "Monthly Marathoner",
    "Consistency Award",
    "Volume Dealer",
    "Progress Pioneer",
    "Class Contributor",
    "Hidden Gem",
    "Sunday Streak",
    "End of Term Champion",
    "One Shot Wonder",
    "Try, Try Again",
    "Never Give Up",
    "Accuracy King",
    "Rapid Recovery",
    "No Mistakes",
    "Careful Checker",
    "Smart Risk-Taker",
    "Puzzle Solver",
    "Test Crusher",
    "Pavonify Bird Lover",
    "Coin Collector",
    "Pavonicoin Hoarder",
    "Big Spender",
    "Trader",
    "Fashionable Peacock",
    "Mystery Box",
    "Lucky Streak",
    "Collector",
    "Trophy Cabinet",
    "Class Champion",
    "Team Player",
    "Peer Motivator",
    "Social Star",
    "House Hero",
    "Friendly Rivalry",
    "Triple Threat",
    "House Collector",
    "Encouragement Chain",
    "Mentor Badge",
    "New Year Kickstart",
    "Summer Sizzler",
    "Winter Warrior",
    "Exam Prep Master",
    "Festival Finisher",
    "Birthday Bonus",
    "Leap Year Learner",
    "Lucky Number 7",
    "Palindrome Day",
    "End of Year Legend",
    "Vocabulary Victor",
    "Grammar Guru",
    "Reading Rock Star",
    "Worksheet Warrior",
    "Multilingual Master",
    "Step by Step",
    "Build a Ladder",
    "Mastermind",
    "Growth Mindset",
    "Pavonify Legend",
]


CATEGORY_RANGES = {
    "Progress/Streaks": range(1, 11),
    "Assignments": range(11, 21),
    "Performance/Scores": range(21, 31),
    "Time/Speed": range(31, 41),
    "Weekly/Monthly": range(41, 51),
    "Accuracy/Attempts": range(51, 61),
    "Gamified": range(61, 71),
    "Social": range(71, 81),
    "Seasonal": range(81, 91),
    "Mastery": range(91, 101),
}

DEFAULTS = {
    "trigger_type": "event",
    "metric": "",
    "comparator": "gte",
    "threshold": 1,
    "window": "none",
    "subject_scope": "any",
    "repeatable": False,
    "cooldown": "none",
    "points": 0,
    "icon": "trophy",
    "rarity": "common",
    "description": "",
    "constraints": {},
}


def category_for_index(index: int) -> str:
    for category, rng in CATEGORY_RANGES.items():
        if index in rng:
            return category
    return "Progress/Streaks"


class Command(BaseCommand):
    help = "Seed the database with initial trophy definitions"

    def handle(self, *args, **options):
        for i, name in enumerate(TROPHY_NAMES, start=1):
            trophy_id = slugify(name)
            data = {
                "id": trophy_id,
                "name": name,
                "category": category_for_index(i),
                **DEFAULTS,
            }
            Trophy.objects.update_or_create(id=trophy_id, defaults=data)
        self.stdout.write(self.style.SUCCESS("Seeded trophies."))
