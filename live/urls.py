"""URL configuration for live game API."""

from rest_framework.routers import DefaultRouter

from .views import LiveGameSessionViewSet

router = DefaultRouter()
router.register(r"", LiveGameSessionViewSet, basename="live-game")

urlpatterns = router.urls
