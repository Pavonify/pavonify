from django.shortcuts import redirect
from functools import wraps

def student_login_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        # Check if the student is logged in using the session
        if 'student_id' not in request.session:
            return redirect('student_login')  # Redirect to the student login page
        return view_func(request, *args, **kwargs)
    return _wrapped_view
