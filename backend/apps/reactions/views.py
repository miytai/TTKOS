"""Views реакций (TECHSPEC §11.6)."""

from rest_framework import mixins, viewsets
from rest_framework.permissions import AllowAny

from .models import Reaction
from .serializers import ReactionSerializer


class ReactionViewSet(mixins.ListModelMixin, mixins.CreateModelMixin,
                      viewsets.GenericViewSet):
    """``GET /api/reactions/`` — справочник типов реакций."""

    queryset = Reaction.objects.all().order_by("order", "id")
    serializer_class = ReactionSerializer
    permission_classes = [AllowAny]
    pagination_class = None
