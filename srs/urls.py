from django.urls import path
from . import views

urlpatterns = [
    path('queue/', views.queue),
    path('attempt/', views.attempt),
    path('my-words/', views.my_words),
    path('word/<int:word_id>/toggle-difficult/', views.toggle_difficult),
    path('stats/summary/', views.stats_summary),
]
