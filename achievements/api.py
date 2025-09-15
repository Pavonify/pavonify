from rest_framework import permissions, viewsets

from .models import Trophy, TrophyUnlock
from .serializers import TrophySerializer, TrophyUnlockSerializer


class TrophyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Trophy.objects.all()
    serializer_class = TrophySerializer
    permission_classes = [permissions.IsAuthenticated]


class TrophyUnlockViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TrophyUnlockSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return TrophyUnlock.objects.filter(user=self.request.user)
