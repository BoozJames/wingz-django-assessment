import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from rides.models import Ride, RideEvent, User

DRIVER_NAMES = [
    ("Chris", "H"), ("Howard", "Y"), ("Randy", "W"), ("Alicia", "M"), ("Priya", "K"),
]
RIDER_NAMES = [
    ("Sam", "Lee"), ("Jordan", "Diaz"), ("Taylor", "Kim"), ("Morgan", "Patel"),
    ("Jamie", "Nguyen"), ("Casey", "Brown"), ("Riley", "Chen"), ("Drew", "Garcia"),
]
STATUSES = [Ride.Status.EN_ROUTE, Ride.Status.PICKUP, Ride.Status.DROPOFF]

# Roughly the San Francisco area, so distance-sort demos return sensible results.
LAT_RANGE = (37.70, 37.83)
LNG_RANGE = (-122.51, -122.36)


class Command(BaseCommand):
    help = "Seeds the database with an admin user plus sample drivers, riders, rides and ride events."

    def add_arguments(self, parser):
        parser.add_argument("--rides", type=int, default=200, help="Number of rides to create.")
        parser.add_argument("--flush", action="store_true", help="Delete existing sample data first.")

    @transaction.atomic
    def handle(self, *args, **options):
        if options["flush"]:
            RideEvent.objects.all().delete()
            Ride.objects.all().delete()
            User.objects.exclude(is_superuser=True).delete()
            self.stdout.write("Cleared existing rides/ride events/non-superuser users.")

        admin_user, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@wingz.example",
                "first_name": "Ada",
                "last_name": "Min",
                "role": User.Role.ADMIN,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if created:
            admin_user.set_password("adminpass123")
            admin_user.save()
            self.stdout.write(self.style.SUCCESS("Created admin user: admin / adminpass123"))
        else:
            self.stdout.write("Admin user already exists: admin")

        drivers = self._get_or_create_users(DRIVER_NAMES, User.Role.DRIVER)
        riders = self._get_or_create_users(RIDER_NAMES, User.Role.RIDER)

        num_rides = options["rides"]
        now = timezone.now()
        created_rides = 0
        for i in range(num_rides):
            pickup_time = now - timedelta(days=random.randint(0, 180), hours=random.randint(0, 23))
            status = random.choice(STATUSES)
            ride = Ride.objects.create(
                status=status,
                rider=random.choice(riders),
                driver=random.choice(drivers),
                pickup_latitude=random.uniform(*LAT_RANGE),
                pickup_longitude=random.uniform(*LNG_RANGE),
                dropoff_latitude=random.uniform(*LAT_RANGE),
                dropoff_longitude=random.uniform(*LNG_RANGE),
                pickup_time=pickup_time,
            )
            created_rides += 1

            # A realistic trip: pickup event, then dropoff some minutes later.
            trip_minutes = random.choice([15, 25, 40, 55, 70, 90, 120])
            pickup_event_time = pickup_time
            dropoff_event_time = pickup_time + timedelta(minutes=trip_minutes)
            RideEvent.objects.create(
                ride=ride, description="Status changed to pickup", created_at=pickup_event_time
            )
            RideEvent.objects.create(
                ride=ride, description="Status changed to dropoff", created_at=dropoff_event_time
            )

            # Sprinkle a few extra events within the last 24h so
            # `todays_ride_events` has something to show in a demo.
            if i < 15:
                recent_time = now - timedelta(hours=random.uniform(0, 23))
                RideEvent.objects.create(
                    ride=ride, description="Driver en route", created_at=recent_time
                )

        self.stdout.write(self.style.SUCCESS(
            f"Seeded {len(drivers)} drivers, {len(riders)} riders, {created_rides} rides."
        ))

    @staticmethod
    def _get_or_create_users(names, role):
        users = []
        for first, last in names:
            username = f"{role}_{first.lower()}_{last.lower()}"
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": first,
                    "last_name": last,
                    "email": f"{first.lower()}.{last.lower()}@wingz.example",
                    "role": role,
                    "phone_number": f"555-{random.randint(1000, 9999)}",
                },
            )
            users.append(user)
        return users
