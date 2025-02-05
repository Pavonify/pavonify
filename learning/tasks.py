from learning.models import Student
from celery import shared_task

@shared_task
def reset_weekly_points():
    """
    Reset weekly points for all students.
    """
    Student.objects.update(weekly_points=0)
    print("Weekly points reset completed!")
