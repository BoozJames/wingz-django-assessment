from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Custom user with a role used to gate API access to admins."""

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        RIDER = "rider", "Rider"
        DRIVER = "driver", "Driver"

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.RIDER)
    phone_number = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = "user"

    def __str__(self):
        return self.get_full_name() or self.username


class Ride(models.Model):
    class Status(models.TextChoices):
        EN_ROUTE = "en-route", "En route"
        PICKUP = "pickup", "Pickup"
        DROPOFF = "dropoff", "Dropoff"

    status = models.CharField(max_length=20, choices=Status.choices, db_index=True)
    rider = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="rides_as_rider", db_column="id_rider"
    )
    driver = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="rides_as_driver", db_column="id_driver"
    )
    pickup_latitude = models.FloatField()
    pickup_longitude = models.FloatField()
    dropoff_latitude = models.FloatField()
    dropoff_longitude = models.FloatField()
    pickup_time = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "ride"

    def __str__(self):
        return f"Ride #{self.pk} ({self.status})"


class RideEvent(models.Model):
    ride = models.ForeignKey(
        Ride, on_delete=models.CASCADE, related_name="ride_events", db_column="id_ride"
    )
    description = models.CharField(max_length=255)
    created_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "ride_event"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.description} @ {self.created_at}"
