import logging
from datetime import timedelta

from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.authtoken.models import Token
from rest_framework.authtoken.serializers import AuthTokenSerializer
from rest_framework.authtoken.views import ObtainAuthToken
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from .distance import InvalidCoordinateError, annotate_distance, parse_coordinate
from .filters import RideFilter
from .models import Ride, RideEvent, User
from .serializers import (
    RideEventWriteSerializer,
    RideListSerializer,
    RideSerializer,
    UserSerializer,
)
from .throttling import LoginRateThrottle

logger = logging.getLogger("rides.security")

ALLOWED_SORT_FIELDS = {"pickup_time", "distance"}
LATITUDE_BOUND = 90.0
LONGITUDE_BOUND = 180.0


class ThrottledObtainAuthToken(ObtainAuthToken):
    """Same behavior as DRF's obtain_auth_token, but actually rate-limited.

    `ObtainAuthToken` hard-codes `throttle_classes = ()` and
    `permission_classes = ()`, which opts it out of the project-wide
    throttle settings - meaning the default view has no brute-force
    protection at all (OWASP A07). This subclass restores throttling
    without touching the (intentionally anonymous) permission behavior.
    """

    throttle_classes = [LoginRateThrottle]

    def post(self, request, *args, **kwargs):
        serializer = AuthTokenSerializer(data=request.data, context={"request": request})
        client_ip = request.META.get("REMOTE_ADDR")
        if not serializer.is_valid():
            logger.warning(
                "Failed login attempt for username=%r from %s",
                request.data.get("username"), client_ip,
            )
            serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        token, _ = Token.objects.get_or_create(user=user)
        logger.info("Successful login for user_id=%s from %s", user.pk, client_ip)
        return Response({"token": token.key})


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
                lat = parse_coordinate(lat, bound=LATITUDE_BOUND, field_name="pickup_latitude")
                lng = parse_coordinate(lng, bound=LONGITUDE_BOUND, field_name="pickup_longitude")
            except InvalidCoordinateError as exc:
                raise ValidationError({"detail": str(exc)})
            queryset = annotate_distance(queryset, lat, lng)

        order_field = f"-{field}" if descending else field
        # `id` is a stable tie-breaker so pagination doesn't skip/repeat rows
        # when many rides share the same pickup_time or distance.
        return queryset.order_by(order_field, "id")
