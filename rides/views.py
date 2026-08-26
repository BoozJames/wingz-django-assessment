from rest_framework import viewsets

from .models import Ride, RideEvent, User
from .serializers import RideEventSerializer, RideSerializer, UserSerializer


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by("id")
    serializer_class = UserSerializer


class RideEventViewSet(viewsets.ModelViewSet):
    queryset = RideEvent.objects.all().order_by("-created_at")
    serializer_class = RideEventSerializer


class RideViewSet(viewsets.ModelViewSet):
    queryset = Ride.objects.select_related("rider", "driver")
    serializer_class = RideSerializer
