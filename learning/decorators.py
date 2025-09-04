from django.shortcuts import redirect
from functools import wraps
from .models import Student

def student_login_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # Check if the student is logged in using the session
        student_id = request.session.get('student_id')
        if not student_id:
            return redirect('student_login')  # Redirect to the student login page
        try:
            student = Student.objects.get(id=student_id)
            student.reset_periodic_points()
            student.save()
        except Student.DoesNotExist:
            del request.session['student_id']
            return redirect('student_login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view
