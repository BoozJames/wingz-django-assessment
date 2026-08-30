from datetime import datetime, timedelta
from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Ride, RideEvent, User


class BaseAPITestCase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin", password="pass1234", role=User.Role.ADMIN
        )
        self.rider = User.objects.create_user(
            username="rider1", password="pass1234", role=User.Role.RIDER,
            email="rider1@example.com", first_name="Rider", last_name="One",
        )
        self.other_rider = User.objects.create_user(
            username="rider2", password="pass1234", role=User.Role.RIDER,
            email="rider2@example.com", first_name="Rider", last_name="Two",
        )
        self.driver = User.objects.create_user(
            username="driver1", password="pass1234", role=User.Role.DRIVER
        )
        self.non_admin = User.objects.create_user(
            username="plain", password="pass1234", role=User.Role.RIDER
        )


class PermissionTests(BaseAPITestCase):
    def test_anonymous_is_rejected(self):
        response = self.client.get("/api/rides/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_admin_is_forbidden(self):
        self.client.force_authenticate(self.non_admin)
        response = self.client.get("/api/rides/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_is_allowed(self):
        self.client.force_authenticate(self.admin)
        response = self.client.get("/api/rides/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class RideListAPITests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.admin)
        now = timezone.now()

        self.ride1 = Ride.objects.create(
            status=Ride.Status.EN_ROUTE, rider=self.rider, driver=self.driver,
            pickup_latitude=37.7749, pickup_longitude=-122.4194,
            dropoff_latitude=37.8, dropoff_longitude=-122.4,
            pickup_time=now - timedelta(hours=2),
        )
        self.ride2 = Ride.objects.create(
            status=Ride.Status.DROPOFF, rider=self.other_rider, driver=self.driver,
            pickup_latitude=37.0, pickup_longitude=-122.0,
            dropoff_latitude=37.1, dropoff_longitude=-122.1,
            pickup_time=now - timedelta(hours=1),
        )

        # One recent event (should show up in todays_ride_events) and one
        # old event (should be excluded) on ride1.
        RideEvent.objects.create(
            ride=self.ride1, description="Status changed to pickup",
            created_at=now - timedelta(hours=1),
        )
        RideEvent.objects.create(
            ride=self.ride1, description="Status changed to dropoff",
            created_at=now - timedelta(days=5),
        )

    def test_todays_ride_events_only_includes_last_24h(self):
        response = self.client.get(f"/api/rides/?status={Ride.Status.EN_ROUTE}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ride_data = response.data["results"][0]
        descriptions = [e["description"] for e in ride_data["todays_ride_events"]]
        self.assertIn("Status changed to pickup", descriptions)
        self.assertNotIn("Status changed to dropoff", descriptions)

    def test_filter_by_status(self):
        response = self.client.get(f"/api/rides/?status={Ride.Status.DROPOFF}")
        ids = [r["id"] for r in response.data["results"]]
        self.assertEqual(ids, [self.ride2.id])

    def test_filter_by_rider_email(self):
        response = self.client.get(f"/api/rides/?rider_email={self.rider.email}")
        ids = [r["id"] for r in response.data["results"]]
        self.assertEqual(ids, [self.ride1.id])

    def test_sort_by_pickup_time(self):
        response = self.client.get("/api/rides/?sort_by=pickup_time")
        ids = [r["id"] for r in response.data["results"]]
        self.assertEqual(ids, [self.ride1.id, self.ride2.id])

    def test_sort_by_pickup_time_descending(self):
        response = self.client.get("/api/rides/?sort_by=-pickup_time")
        ids = [r["id"] for r in response.data["results"]]
        self.assertEqual(ids, [self.ride2.id, self.ride1.id])

    def test_sort_by_distance_requires_coordinates(self):
        response = self.client.get("/api/rides/?sort_by=distance")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sort_by_distance(self):
        # Point close to ride1's pickup location.
        response = self.client.get(
            "/api/rides/?sort_by=distance&pickup_latitude=37.77&pickup_longitude=-122.42"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [r["id"] for r in response.data["results"]]
        self.assertEqual(ids, [self.ride1.id, self.ride2.id])
        self.assertLess(response.data["results"][0]["distance"], response.data["results"][1]["distance"])

    def test_ride_list_query_count_is_bounded(self):
        # 1 COUNT (pagination) + 1 ride query (joined to rider/driver)
        # + 1 prefetch query for today's ride events = 3 total, regardless
        # of how many rides/events exist.
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/api/rides/")
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertLessEqual(len(ctx.captured_queries), 3)

    def test_pagination_present(self):
        response = self.client.get("/api/rides/")
        for key in ("count", "next", "previous", "results"):
            self.assertIn(key, response.data)

    def test_sort_by_distance_rejects_non_finite_coordinates(self):
        for lat, lng in [("nan", "0"), ("inf", "0"), ("0", "-inf")]:
            response = self.client.get(
                f"/api/rides/?sort_by=distance&pickup_latitude={lat}&pickup_longitude={lng}"
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_sort_by_distance_rejects_out_of_range_coordinates(self):
        response = self.client.get(
            "/api/rides/?sort_by=distance&pickup_latitude=999&pickup_longitude=0"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class UserPasswordSecurityTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.client.force_authenticate(self.admin)

    def test_created_user_password_is_hashed_and_never_returned(self):
        response = self.client.post("/api/users/", {
            "first_name": "New", "last_name": "Hire", "email": "new.hire@example.com",
            "role": User.Role.RIDER, "password": "S0me-Str0ng-Passw0rd!",
        })
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertNotIn("password", response.data)

        created = User.objects.get(pk=response.data["id"])
        self.assertNotEqual(created.password, "S0me-Str0ng-Passw0rd!")
        self.assertTrue(created.check_password("S0me-Str0ng-Passw0rd!"))

    def test_weak_password_is_rejected(self):
        response = self.client.post("/api/users/", {
            "first_name": "Weak", "last_name": "Pw", "email": "weak.pw@example.com",
            "role": User.Role.RIDER, "password": "1234",
        })
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class LoginThrottleTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_repeated_failed_logins_are_throttled(self):
        # settings.py configures the 'login' throttle scope at 5/min.
        for _ in range(5):
            response = self.client.post(
                "/api/api-token-auth/", {"username": "admin", "password": "wrong"}
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        throttled = self.client.post(
            "/api/api-token-auth/", {"username": "admin", "password": "wrong"}
        )
        self.assertEqual(throttled.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_valid_login_issues_a_token(self):
        response = self.client.post(
            "/api/api-token-auth/", {"username": "admin", "password": "pass1234"}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("token", response.data)


class TripDurationReportCommandTests(TestCase):
    """Covers the `trip_duration_report` management command (bonus SQL report)."""

    def setUp(self):
        self.driver = User.objects.create_user(
            username="driver_report", password="x", role=User.Role.DRIVER,
            first_name="Jamie", last_name="Ortiz",
        )
        self.rider = User.objects.create_user(
            username="rider_report", password="x", role=User.Role.RIDER
        )

    def _make_ride_with_events(self, pickup_time, trip_minutes):
        ride = Ride.objects.create(
            status=Ride.Status.DROPOFF, rider=self.rider, driver=self.driver,
            pickup_latitude=0, pickup_longitude=0, dropoff_latitude=0, dropoff_longitude=0,
            pickup_time=pickup_time,
        )
        RideEvent.objects.create(
            ride=ride, description="Status changed to pickup", created_at=pickup_time
        )
        RideEvent.objects.create(
            ride=ride, description="Status changed to dropoff",
            created_at=pickup_time + timedelta(minutes=trip_minutes),
        )
        return ride

    def test_report_counts_only_trips_over_one_hour(self):
        pickup_time = timezone.make_aware(datetime(2026, 3, 15, 10, 0, 0))
        self._make_ride_with_events(pickup_time, 90)  # > 1hr: counted
        self._make_ride_with_events(pickup_time, 30)  # <= 1hr: excluded

        out = StringIO()
        call_command("trip_duration_report", stdout=out)
        output = out.getvalue()

        self.assertIn("2026-03", output)
        self.assertIn("Jamie O", output)
        lines = [line for line in output.splitlines() if "2026-03" in line]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].rstrip().endswith("1"))

    def test_report_handles_no_matching_trips(self):
        out = StringIO()
        call_command("trip_duration_report", stdout=out)
        self.assertIn("No trips longer than 1 hour found.", out.getvalue())
