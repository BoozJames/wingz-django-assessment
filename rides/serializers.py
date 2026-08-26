from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Ride, RideEvent, User


class UserSerializer(serializers.ModelSerializer):
    # write_only: a password hash must never be echoed back in a response
    # (OWASP A02 - Cryptographic Failures). Optional so existing clients that
    # don't manage passwords through this endpoint are unaffected.
    password = serializers.CharField(
        write_only=True, required=False, style={"input_type": "password"}
    )

    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "email", "phone_number", "role", "password"]

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = User(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


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
