from datetime import timedelta

from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError

from .distance import annotate_distance
from .filters import RideFilter
from .models import Ride, RideEvent, User
from .serializers import (
    RideEventWriteSerializer,
    RideListSerializer,
    RideSerializer,
    UserSerializer,
)

ALLOWED_SORT_FIELDS = {"pickup_time", "distance"}


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all().order_by("id")
    serializer_class = UserSerializer


class RideEventViewSet(viewsets.ModelViewSet):
    queryset = RideEvent.objects.all().order_by("-created_at")
    serializer_class = RideEventWriteSerializer


class RideViewSet(viewsets.ModelViewSet):
    filterset_class = RideFilter

    def get_serializer_class(self):
        if self.action == "list":
            return RideListSerializer
        return RideSerializer

    def get_queryset(self):
        queryset = Ride.objects.select_related("rider", "driver")

        if self.action == "list":
            since = timezone.now() - timedelta(hours=24)
            # Only the last 24h of events are ever loaded from the DB, and
            # they are fetched in a single extra query (via Prefetch) that
            # covers every ride in the current page - never the full
            # RideEvent history for a ride.
            todays_events_qs = RideEvent.objects.filter(created_at__gte=since)
            queryset = queryset.prefetch_related(
                Prefetch("ride_events", queryset=todays_events_qs, to_attr="todays_ride_events")
            )

        return queryset

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)

        if self.action != "list":
            return queryset

        sort_by = self.request.query_params.get("sort_by", "pickup_time")
        descending = sort_by.startswith("-")
        field = sort_by[1:] if descending else sort_by

        if field not in ALLOWED_SORT_FIELDS:
            raise ValidationError(
                {"sort_by": f"Must be one of {sorted(ALLOWED_SORT_FIELDS)}, optionally prefixed with '-'."}
            )

        if field == "distance":
            lat = self.request.query_params.get("pickup_latitude")
            lng = self.request.query_params.get("pickup_longitude")
            if lat is None or lng is None:
                raise ValidationError(
                    {"pickup_latitude": "Required when sort_by=distance.",
                     "pickup_longitude": "Required when sort_by=distance."}
                )
            try:
                lat, lng = float(lat), float(lng)
            except ValueError:
                raise ValidationError({"pickup_latitude": "Must be a valid float.",
                                        "pickup_longitude": "Must be a valid float."})
            queryset = annotate_distance(queryset, lat, lng)

        order_field = f"-{field}" if descending else field
        # `id` is a stable tie-breaker so pagination doesn't skip/repeat rows
        # when many rides share the same pickup_time or distance.
        return queryset.order_by(order_field, "id")
