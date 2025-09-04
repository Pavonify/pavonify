from learning.models import Student
from celery import shared_task
from django.utils.timezone import now

@shared_task
def reset_weekly_points():
    """Reset weekly points for all students."""
    today = now().date()
    Student.objects.update(weekly_points=0, weekly_points_last_reset=today)
    print("Weekly points reset completed!")


@shared_task
def reset_monthly_points():
    """Reset monthly points for all students."""
    today = now().date()
    Student.objects.update(monthly_points=0, monthly_points_last_reset=today)
    print("Monthly points reset completed!")
