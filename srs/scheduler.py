from datetime import timedelta
from django.utils import timezone

INTERVALS = [
    {"label": "4h", "hours": 4},
    {"label": "12h", "hours": 12},
    {"label": "24h", "hours": 24},
    {"label": "6d", "hours": 6*24},
    {"label": "12d", "hours": 12*24},
    {"label": "48d", "hours": 48*24},
    {"label": "96d", "hours": 96*24},
    {"label": "6mo", "hours": 180*24},
]

ACTIVITIES_ORDER = ["exposure", "tapping", "mcq", "typing", "listening"]


def compute_strength(progress):
    base = (progress.box_index / 7) * 100
    if progress.next_due_at and progress.next_due_at < timezone.now():
        overdue_days = (timezone.now() - progress.next_due_at).days
        base -= min(40, 10 * overdue_days)
    return max(0, round(base))


def suggest_activity(prev_activity=None, is_correct=True, has_audio=False):
    if prev_activity is None:
        return "exposure" if not has_audio else "listening"
    order = ACTIVITIES_ORDER.copy()
    if not has_audio and "listening" in order:
        order.remove("listening")
    if prev_activity not in order:
        return order[0]
    idx = order.index(prev_activity)
    if is_correct:
        idx = (idx + 1) % len(order)
    else:
        idx = max(0, idx - 1)
    return order[idx]


def update_progress(progress, is_correct):
    now = timezone.now()
    if is_correct:
        progress.box_index = min(progress.box_index + 1, 7)
        progress.streak += 1
        progress.times_correct += 1
    else:
        progress.box_index = 0
        progress.streak = 0
        progress.times_incorrect += 1
        progress.is_difficult = True
    interval_hours = INTERVALS[progress.box_index]["hours"]
    progress.next_due_at = now + timedelta(hours=interval_hours)
    progress.last_seen_at = now
    progress.strength = compute_strength(progress)
    if progress.status == "new":
        progress.status = "learning"
    if progress.status == "learning" and progress.box_index >= 2:
        progress.status = "reviewing"
    if progress.status == "reviewing" and progress.box_index >= 6 and progress.streak >= 3:
        progress.status = "mastered"
    progress.save()
    return progress
