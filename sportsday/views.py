"""Views for the Sports Day module."""
from __future__ import annotations

import io

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView, TemplateView

from . import forms, models, services


class AccessRequiredMixin(LoginRequiredMixin):
    """Mixin that checks for the sports day access cookie."""

    def dispatch(self, request: HttpRequest, *args, **kwargs):
        config = models.SportsdayAccessConfig.get_solo()
        if not config.is_enabled or config.cookie_valid(request):
            return super().dispatch(request, *args, **kwargs)
        return redirect("sportsday:access")


class MeetMixin:
    meet_slug_kwarg = "slug"

    def get_meet(self) -> models.Meet:
        slug = self.kwargs.get(self.meet_slug_kwarg)
        return get_object_or_404(models.Meet, slug=slug)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["meet"] = self.get_meet()
        return context


class AccessView(View):
    template_name = "sportsday/access.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        form = forms.AccessCodeForm()
        return render(request, self.template_name, {"form": form})

    def post(self, request: HttpRequest) -> HttpResponse:
        form = forms.AccessCodeForm(request.POST)
        config = models.SportsdayAccessConfig.get_solo()
        if not form.is_valid():
            return render(request, self.template_name, {"form": form})
        code = form.cleaned_data["code"]
        if not config.code_hash:
            messages.error(request, "No access code has been configured yet.")
            return render(request, self.template_name, {"form": form})
        if models.SportsdayAccessConfig.verify_code(code, config.code_hash):
            response = redirect("sportsday:meet_list")
            config.issue_cookie(response, request.user if request.user.is_authenticated else None)
            models.AuditLog.objects.create(
                user=request.user if request.user.is_authenticated else None,
                action="ACCESS_GRANTED",
                payload={"ip": request.META.get("REMOTE_ADDR")},
            )
            return response
        models.AuditLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            action="ACCESS_DENIED",
            payload={"ip": request.META.get("REMOTE_ADDR")},
        )
        messages.error(request, "Invalid access code. Please try again.")
        return render(request, self.template_name, {"form": form})


class MeetListView(AccessRequiredMixin, TemplateView):
    template_name = "sportsday/meet_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["meets"] = models.Meet.objects.all()
        return context


class DashboardView(AccessRequiredMixin, MeetMixin, TemplateView):
    template_name = "sportsday/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        meet = self.get_meet()
        context.update(
            {
                "events": meet.events.count(),
                "students": models.Student.objects.count(),
                "entries": models.Entry.objects.filter(event__meet=meet).count(),
                "rules": meet.scoring_rules.all(),
            }
        )
        return context


class StudentListView(AccessRequiredMixin, MeetMixin, ListView):
    model = models.Student
    template_name = "sportsday/students_list.html"
    context_object_name = "students"
    paginate_by = 50

    def get_queryset(self):
        qs = super().get_queryset().filter(is_active=True)
        grade = self.request.GET.get("grade")
        house = self.request.GET.get("house")
        gender = self.request.GET.get("gender")
        if grade:
            qs = qs.filter(grade=grade)
        if house:
            qs = qs.filter(house__iexact=house)
        if gender:
            qs = qs.filter(gender__iexact=gender)
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        meet = self.get_meet()
        entries = models.Entry.objects.filter(event__meet=meet)
        counts = entries.values_list("student", flat=True).distinct().count()
        context.update(
            {
                "meet": meet,
                "entry_count": counts,
            }
        )
        return context


class StudentUploadView(AccessRequiredMixin, MeetMixin, View):
    template_name = "sportsday/students_upload.html"

    def get(self, request: HttpRequest, slug: str) -> HttpResponse:
        form = forms.StudentUploadForm()
        return render(request, self.template_name, {"form": form, "meet": self.get_meet()})

    def post(self, request: HttpRequest, slug: str) -> HttpResponse:
        form = forms.StudentUploadForm(request.POST, request.FILES)
        meet = self.get_meet()
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "meet": meet})
        uploaded = form.cleaned_data["file"]
        content = uploaded.read().decode("utf-8")
        buffer = io.StringIO(content)
        try:
            rows = services.load_students_from_csv(meet, buffer, user=request.user if request.user.is_authenticated else None)
        except services.CSVImportError as exc:
            messages.error(request, str(exc))
            return render(request, self.template_name, {"form": form, "meet": meet})
        messages.success(request, f"Imported {len(rows)} student rows successfully.")
        return redirect("sportsday:students", slug=meet.slug)


class LeaderboardView(AccessRequiredMixin, MeetMixin, TemplateView):
    template_name = "sportsday/leaderboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        meet = self.get_meet()
        leaderboard = build_simple_leaderboard(meet)
        context.update({"leaderboard": leaderboard})
        return context


def build_simple_leaderboard(meet: models.Meet) -> list[dict[str, object]]:
    entries = models.Entry.objects.filter(event__meet=meet).select_related("student", "event")
    scoring_rule = meet.scoring_rules.filter(scope=models.ScoringRule.SCOPE_EVENT).first()
    if not scoring_rule:
        return []
    house_points: dict[str, int] = {}
    for entry in entries:
        result = getattr(entry, "result", None)
        if not result or result.rank is None:
            continue
        ranks = [result.rank]
        points = services.allocate_points(entry.event, scoring_rule, ranks)
        if points and points[0]:
            house_points.setdefault(entry.student.house, 0)
            house_points[entry.student.house] += points[0]
    return [
        {"house": house, "points": points}
        for house, points in sorted(house_points.items(), key=lambda item: item[1], reverse=True)
    ]


class StudentsAPI(AccessRequiredMixin, MeetMixin, View):
    def get(self, request: HttpRequest, slug: str) -> JsonResponse:
        meet = self.get_meet()
        qs = models.Student.objects.all()
        q = request.GET.get("q")
        if q:
            qs = qs.filter(Q(last_name__icontains=q) | Q(first_name__icontains=q))
        grade = request.GET.get("grade")
        if grade:
            qs = qs.filter(grade=grade)
        house = request.GET.get("house")
        if house:
            qs = qs.filter(house__iexact=house)
        data = [
            {
                "id": student.id,
                "name": student.full_name,
                "grade": student.grade,
                "house": student.house,
                "gender": student.gender,
            }
            for student in qs[:200]
        ]
        return JsonResponse({"students": data})


class EventsAPI(AccessRequiredMixin, MeetMixin, View):
    def get(self, request: HttpRequest, slug: str) -> JsonResponse:
        meet = self.get_meet()
        data = [
            {
                "id": event.id,
                "name": event.name,
                "type": event.event_type,
                "gender": event.gender_limit,
                "rounds": event.rounds,
                "capacity": event.capacity,
            }
            for event in meet.events.all()
        ]
        return JsonResponse({"events": data})


class LeaderboardAPI(AccessRequiredMixin, MeetMixin, View):
    def get(self, request: HttpRequest, slug: str) -> JsonResponse:
        meet = self.get_meet()
        scope = request.GET.get("scope", "overall")
        leaderboard = build_simple_leaderboard(meet)
        return JsonResponse({"scope": scope, "leaderboard": leaderboard})
