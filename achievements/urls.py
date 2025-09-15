from rest_framework.routers import DefaultRouter

from .api import TrophyViewSet, TrophyUnlockViewSet

router = DefaultRouter()
router.register(r'trophies', TrophyViewSet, basename='trophy')
router.register(r'unlocks', TrophyUnlockViewSet, basename='trophy-unlock')

urlpatterns = router.urls
