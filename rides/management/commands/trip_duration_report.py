from django.core.management.base import BaseCommand, CommandError
from django.db import connection

# Backend-specific versions of the bonus SQL report documented in README.md
# ("trips whose pickup-to-dropoff duration exceeded 1 hour, by month and
# driver"). The join/aggregation logic is identical in both - only the
# date-diff and string-formatting syntax differs per database.
#
# Table/column names here match this project's actual schema (Django's
# default `id` primary key on every table, plus the FK columns
# id_rider/id_driver/id_ride), which differs slightly from the spec's
# id_ride/id_user/id_ride_event primary-key naming used in the README's
# spec-schema version of this query.
_SQLITE_QUERY = """
SELECT
    strftime('%Y-%m', pickup_event.created_at)                    AS month,
    driver.first_name || ' ' || substr(driver.last_name, 1, 1)    AS driver,
    COUNT(*)                                                        AS trips_over_1hr
FROM ride
JOIN "user" AS driver
    ON driver.id = ride.id_driver
JOIN ride_event AS pickup_event
    ON pickup_event.id_ride = ride.id
   AND pickup_event.description = 'Status changed to pickup'
JOIN ride_event AS dropoff_event
    ON dropoff_event.id_ride = ride.id
   AND dropoff_event.description = 'Status changed to dropoff'
   AND dropoff_event.created_at > pickup_event.created_at
WHERE (julianday(dropoff_event.created_at) - julianday(pickup_event.created_at)) * 24 > 1
GROUP BY month, driver.id, driver.first_name, driver.last_name
ORDER BY month, driver;
"""

_POSTGRESQL_QUERY = """
SELECT
    TO_CHAR(pickup_event.created_at, 'YYYY-MM')                 AS month,
    CONCAT(driver.first_name, ' ', LEFT(driver.last_name, 1))   AS driver,
    COUNT(*)                                                     AS trips_over_1hr
FROM ride
JOIN "user" AS driver
    ON driver.id = ride.id_driver
JOIN ride_event AS pickup_event
    ON pickup_event.id_ride = ride.id
   AND pickup_event.description = 'Status changed to pickup'
JOIN ride_event AS dropoff_event
    ON dropoff_event.id_ride = ride.id
   AND dropoff_event.description = 'Status changed to dropoff'
   AND dropoff_event.created_at > pickup_event.created_at
WHERE dropoff_event.created_at - pickup_event.created_at > INTERVAL '1 hour'
GROUP BY month, driver.id, driver.first_name, driver.last_name
ORDER BY month, driver;
"""

_QUERY_BY_VENDOR = {
    "sqlite": _SQLITE_QUERY,
    "postgresql": _POSTGRESQL_QUERY,
}


class Command(BaseCommand):
    help = (
        "Prints the bonus report from the assessment: count of trips whose "
        "pickup-to-dropoff duration exceeded 1 hour, grouped by month and "
        "driver. Runs the raw SQL documented in README.md against the "
        "current database (auto-selected by backend)."
    )

    def handle(self, *args, **options):
        vendor = connection.vendor
        query = _QUERY_BY_VENDOR.get(vendor)
        if query is None:
            raise CommandError(
                f"No trip-duration report SQL is defined for database backend '{vendor}'. "
                "See README.md's 'Bonus: SQL report' section for the SQLite/PostgreSQL "
                "versions to adapt."
            )

        with connection.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()

        if not rows:
            self.stdout.write("No trips longer than 1 hour found.")
            return

        header = ("Month", "Driver", "Count of Trips > 1 hr")
        widths = [
            max(len(header[i]), *(len(str(row[i])) for row in rows))
            for i in range(len(header))
        ]
        self.stdout.write("  ".join(h.ljust(w) for h, w in zip(header, widths)))
        self.stdout.write("  ".join("-" * w for w in widths))
        for row in rows:
            self.stdout.write("  ".join(str(v).ljust(w) for v, w in zip(row, widths)))
