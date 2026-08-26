from rest_framework import serializers

from .models import Ride, RideEvent, User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "email", "phone_number", "role"]


class RideEventSerializer(serializers.ModelSerializer):
    """Nested representation used inside the Ride List API response."""

    id_ride = serializers.IntegerField(source="ride_id", read_only=True)

    class Meta:
        model = RideEvent
        fields = ["id", "id_ride", "description", "created_at"]


class RideEventWriteSerializer(serializers.ModelSerializer):
    """Used by the standalone RideEvent CRUD endpoint."""

    class Meta:
        model = RideEvent
        fields = ["id", "ride", "description", "created_at"]


class RideListSerializer(serializers.ModelSerializer):
    """Read-optimized serializer for the Ride List API.

    Relies entirely on data already fetched by the view's queryset
    (select_related for rider/driver, Prefetch(..., to_attr="todays_ride_events")
    for the last-24h events) so serializing a page never issues extra queries.
    """

    id_rider = serializers.IntegerField(source="rider_id", read_only=True)
    id_driver = serializers.IntegerField(source="driver_id", read_only=True)
    rider = UserSerializer(read_only=True)
    driver = UserSerializer(read_only=True)
    todays_ride_events = serializers.SerializerMethodField()
    distance = serializers.SerializerMethodField()

    class Meta:
        model = Ride
        fields = [
            "id",
            "status",
            "id_rider",
            "id_driver",
            "rider",
            "driver",
            "pickup_latitude",
            "pickup_longitude",
            "dropoff_latitude",
            "dropoff_longitude",
            "pickup_time",
            "todays_ride_events",
            "distance",
        ]

    def get_todays_ride_events(self, obj):
        # `todays_ride_events` is populated by a Prefetch(to_attr=...) in the
        # view's queryset - reading it here never issues a SQL query.
        events = getattr(obj, "todays_ride_events", [])
        return RideEventSerializer(events, many=True).data

    def get_distance(self, obj):
        # Only present when the queryset was annotated for distance sorting.
        distance = getattr(obj, "distance", None)
        return round(distance, 3) if distance is not None else None


class RideSerializer(serializers.ModelSerializer):
    """Standard CRUD serializer for the Ride ViewSet (create/update/retrieve)."""

    class Meta:
        model = Ride
        fields = [
            "id",
            "status",
            "rider",
            "driver",
            "pickup_latitude",
            "pickup_longitude",
            "dropoff_latitude",
            "dropoff_longitude",
            "pickup_time",
        ]
