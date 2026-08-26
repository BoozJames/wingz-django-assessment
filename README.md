# Wingz Ride API

A Django REST Framework API for managing ride information, built for the
Wingz Python/Django Developer Test.

## Stack

- Python 3.11, Django 5.2, Django REST Framework 3.18, django-filter 26
- SQLite for local development (default Django settings, zero setup)
- python-dotenv for loading `DJANGO_SECRET_KEY` / `DJANGO_DEBUG` / `DJANGO_ALLOWED_HOSTS` from a local `.env` file (see [Security](#security))

## Setup

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd Technical

# 2. Create and activate a virtual environment
python -m venv venv
source venv/Scripts/activate      # Windows (git-bash)
# venv\Scripts\activate.bat       # Windows (cmd)
# source venv/bin/activate        # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run migrations
python manage.py migrate

# 5. Seed sample data (creates an admin user + drivers/riders/rides/ride events)
python manage.py seed_data --rides 200

# 6. Run the server
python manage.py runserver
```

The seed command prints the admin credentials it creates:

```
username: admin
password: adminpass123
```

(You can also run `python manage.py createsuperuser` and set `role='admin'` on it via `/admin/`.)

No `.env` file is required for local development — `DJANGO_DEBUG` defaults to `True`
with a dev-only fallback secret key. Copy `.env.example` to `.env` only when you need to
override those defaults (e.g. to test production settings locally).

## Authentication

All API endpoints require a user whose `role` is `'admin'` (see `rides/permissions.py::IsAdminRole`).
Two authentication methods are enabled:

- **Token auth** (for API clients): obtain a token, then send it as a header.
  ```bash
  curl -X POST http://localhost:8000/api/api-token-auth/ \
       -d "username=admin&password=adminpass123"
  # -> {"token": "..."}

  curl http://localhost:8000/api/rides/ -H "Authorization: Token <token>"
  ```
- **Session auth** (for browsing the API in a browser): log in at `/admin/` or
  via the DRF browsable API login, then visit `/api/rides/` directly.

## Endpoints

| Endpoint            | Methods                  | Notes                                   |
|---------------------|---------------------------|------------------------------------------|
| `/api/users/`        | full CRUD                | |
| `/api/rides/`        | full CRUD (`list` optimized, see below) | |
| `/api/ride-events/`  | full CRUD                | |
| `/api/api-token-auth/` | POST                    | exchange username/password for a token |

### Ride List API (`GET /api/rides/`)

Query parameters:

- `status` — exact match against `Ride.status` (`en-route`, `pickup`, `dropoff`).
- `rider_email` — exact match (case-insensitive) against the rider's email.
- `sort_by` — one of `pickup_time`, `-pickup_time`, `distance`, `-distance`.
  Defaults to `pickup_time`.
- `pickup_latitude`, `pickup_longitude` — **required** when `sort_by=distance`
  (or `-distance`); the point to measure distance from.
- `page`, `page_size` — standard DRF page-number pagination (`page_size` capped at 200).

Example:

```
GET /api/rides/?status=en-route&rider_email=rider1@example.com&sort_by=-distance&pickup_latitude=37.77&pickup_longitude=-122.42&page=2
```

Each ride in the response includes:

- `id_rider`, `id_driver` — the raw foreign key ids.
- `rider`, `driver` — the full nested user objects.
- `todays_ride_events` — only the `RideEvent`s from the last 24 hours for that ride.
- `distance` — populated (in km) only when `sort_by=distance`/`-distance` was used.

## Design decisions & performance notes

### Query efficiency for the Ride List API

The view (`rides/views.py::RideViewSet.get_queryset`) builds the list queryset as:

```python
Ride.objects.select_related("rider", "driver").prefetch_related(
    Prefetch("ride_events", queryset=RideEvent.objects.filter(created_at__gte=last_24h),
             to_attr="todays_ride_events")
)
```

- `select_related` joins `rider`/`driver` into the **same** query as the rides — no per-row user queries.
- `Prefetch(..., to_attr="todays_ride_events")` issues **one extra query** that fetches
  only `RideEvent` rows from the last 24 hours, and only for the rides on the current
  page (`WHERE id_ride IN (...)`). It never loads a ride's full event history — this is
  the "advanced Django feature" used to satisfy the requirement that the RideEvent table's
  size can't affect this endpoint's cost.
- The serializer reads `obj.todays_ride_events` (a plain Python list set by the prefetch),
  so serializing never triggers additional queries.

Total queries for `GET /api/rides/`: **1 COUNT** (pagination) + **1** ride+rider+driver
query + **1** ride-events prefetch = **3 queries**, regardless of table size or page size.
This is verified in `rides/tests.py::RideListAPITests.test_ride_list_query_count_is_bounded`.

### Sorting by pickup_time vs. distance, efficiently

Both sort modes are handled by `RideViewSet.filter_queryset` and applied via `order_by()`
**before** the queryset is evaluated, so the database — not Python — does the sorting and
pagination (`LIMIT`/`OFFSET`) still uses a normal indexed/orderable query:

- `sort_by=pickup_time` — a plain `order_by("pickup_time")`. The `Ride.pickup_time`
  column has a DB index (`db_index=True` in the model) to keep this fast on a large table.
- `sort_by=distance` — `rides/distance.py::annotate_distance` annotates the queryset with
  a `distance` field computed via the **Haversine formula**, expressed entirely with Django
  ORM math functions (`Radians`, `Sin`, `Cos`, `ATan2`, `Sqrt`, `Power`). The database
  computes and orders by this expression directly — the full ride table is never pulled
  into Python to be sorted there.

  **Caveat**: because the schema is fixed as plain `FLOAT` columns (no PostGIS/geo
  extension allowed per the assessment), the database still has to compute the distance
  per row — there's no spatial index it can use to prune rows before sorting. For a
  genuinely huge table in production, the recommended upgrade is a PostGIS `PointField`
  with a GiST index, so `order_by()` can use the `<->` KNN operator instead of a computed
  expression sort. That requires changing the Ride table structure, which the assessment
  says to assume is off the table.

Both sort orders add `id` as a stable tie-breaker (`order_by(field, "id")`) so that
pagination doesn't skip or repeat rows when many rides share the same `pickup_time` or
computed `distance`.

### Custom User model

`rides.User` extends `AbstractUser` with a `role` field (`admin` / `rider` / `driver`)
and `phone_number`, and is wired up as `AUTH_USER_MODEL`. Access control checks this
`role` field (`rides/permissions.py::IsAdminRole`), which is distinct from Django's
built-in `is_staff`/`is_superuser` flags used only for the Django admin site.

### Filtering

Implemented with `django-filter` (`rides/filters.py::RideFilter`), wired in as the
default `DjangoFilterBackend` — kept declarative and easy to extend with more fields
later.

## Bonus: SQL report — trips over 1 hour, by month and driver

Table names/columns follow the assessment's schema (`Ride`, `Ride_Event`, `User`).
Each ride's duration is derived from the timestamps of its `'Status changed to pickup'`
and `'Status changed to dropoff'` `Ride_Event` rows.

```sql
SELECT
    TO_CHAR(pickup_event.created_at, 'YYYY-MM')                    AS month,
    CONCAT(driver.first_name, ' ', LEFT(driver.last_name, 1))      AS driver,
    COUNT(*)                                                        AS count_of_trips_over_1hr
FROM "Ride" AS ride
JOIN "User" AS driver
    ON driver.id_user = ride.id_driver
JOIN "Ride_Event" AS pickup_event
    ON pickup_event.id_ride = ride.id_ride
   AND pickup_event.description = 'Status changed to pickup'
JOIN "Ride_Event" AS dropoff_event
    ON dropoff_event.id_ride = ride.id_ride
   AND dropoff_event.description = 'Status changed to dropoff'
   AND dropoff_event.created_at > pickup_event.created_at
WHERE dropoff_event.created_at - pickup_event.created_at > INTERVAL '1 hour'
GROUP BY
    TO_CHAR(pickup_event.created_at, 'YYYY-MM'),
    driver.id_user,
    driver.first_name,
    driver.last_name
ORDER BY month, driver;
```

Notes:

- `TO_CHAR(..., 'YYYY-MM')` and `INTERVAL '1 hour'` are PostgreSQL syntax. For SQLite,
  replace with `strftime('%Y-%m', pickup_event.created_at)` and compare
  `(julianday(dropoff_event.created_at) - julianday(pickup_event.created_at)) * 24 > 1`.
- Grouping by `driver.id_user` (in addition to the display name) avoids merging two
  different drivers who happen to share a first-name/last-initial combination.
- The join conditions on `pickup_event`/`dropoff_event` assume exactly one pickup and one
  dropoff event per completed ride, as stated in the assessment.

## Running tests

```bash
python manage.py test rides
```

Covers: permission enforcement (anonymous/non-admin/admin), status and rider-email
filtering, both sort modes (including validation errors for missing/non-finite/out-of-range
coordinates), pagination shape, the `todays_ride_events` 24-hour cutoff, the bounded
query-count guarantee for the Ride List API, password hashing on user creation, weak-password
rejection, and login throttling.

## Sample data

`python manage.py seed_data [--rides N] [--flush]` creates:

- One admin user (`admin` / `adminpass123`).
- A handful of drivers and riders.
- `N` rides (default 200) with randomized SF-area coordinates and pickup times spread
  over the last ~6 months, each with paired pickup/dropoff `Ride_Event`s (so the bonus
  SQL report has data to aggregate), plus a few recent events for `todays_ride_events`
  to demonstrate against.

## Security

Mapped against the OWASP API/Top 10 categories most relevant to this project:

| Category | What's done | Where |
|---|---|---|
| **A01 Broken Access Control** | Every endpoint defaults to deny; `IsAdminRole` requires an authenticated user whose `role == 'admin'` (distinct from Django's `is_staff`/`is_superuser`). Denied attempts by authenticated users are logged. | `rides/permissions.py` |
| **A02 Cryptographic Failures** | Passwords are never stored or returned in plaintext — `UserSerializer` hashes via `set_password()`/Django's validators and the field is `write_only`. `SECRET_KEY` is read from the environment, never committed. Production (`DEBUG=False`) forces `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, HSTS, and SSL redirect. | `rides/serializers.py`, `wingz_api/settings.py` |
| **A03 Injection** | 100% Django ORM — no raw SQL, `.extra()`, or string-built queries anywhere in the executable code (the bonus report query is documentation only, never executed by the app). User-supplied floats for distance sorting are bound as parameterized `Value()` expressions, never interpolated into SQL. | `rides/distance.py` |
| **A04 Insecure Design** | Distance-sort coordinates are validated as finite, in-range numbers before use — a bare `float()` call would otherwise accept `"nan"`/`"inf"` and silently corrupt every row's computed ordering. Serializers use explicit `fields` allow-lists (never `"__all__"`), so new model fields aren't accidentally exposed for mass assignment. | `rides/distance.py::parse_coordinate`, `rides/serializers.py` |
| **A05 Security Misconfiguration** | `DEBUG`/`SECRET_KEY`/`ALLOWED_HOSTS` come from the environment; the app refuses to start with `DEBUG=False` unless a real secret key and explicit allowed hosts are set. `X_FRAME_OPTIONS`, `SECURE_CONTENT_TYPE_NOSNIFF`, `SESSION_COOKIE_HTTPONLY` are on unconditionally. | `wingz_api/settings.py` |
| **A06 Vulnerable/Outdated Components** | Dependencies are pinned in `requirements.txt`; run `pip list --outdated` periodically and re-run the test suite after bumping versions. | `requirements.txt` |
| **A07 Auth Failures** | The token-login endpoint is rate-limited (`5/min` per IP) — DRF's stock `obtain_auth_token` view explicitly disables throttling, so a custom `ThrottledObtainAuthToken` restores it. All other endpoints are throttled too (`30/min` anon, `120/min` authenticated) as defense in depth. Django's standard password validators (min length, common-password, similarity, numeric-only checks) apply to any password set through the API. | `rides/throttling.py`, `rides/views.py::ThrottledObtainAuthToken` |
| **A09 Logging & Monitoring Failures** | Failed logins, successful logins, and denied-permission attempts are logged (to `rides.security` / console) with the acting user id and path — enough to spot brute-force or privilege-escalation attempts after the fact, without logging credentials. | `rides/permissions.py`, `rides/views.py` |

Notes / things intentionally left out of scope:

- **CORS**: not configured, since this API isn't paired with a browser frontend in this
  assessment. If one is added, install `django-cors-headers` and set an explicit
  `CORS_ALLOWED_ORIGINS` allow-list — never `CORS_ALLOW_ALL_ORIGINS = True`.
- **Token expiry**: DRF's `Token` model doesn't expire. For production, swap to
  `djangorestframework-simplejwt` (short-lived access tokens + refresh) or add a
  scheduled job to rotate/expire stale tokens.
- **A08 (Software/Data Integrity)** and **A10 (SSRF)** aren't applicable — there's no
  deserialization of untrusted data beyond DRF's JSON parser, and the app makes no
  outbound requests based on user input.

## Known limitations / possible follow-ups

- Distance sorting computes Haversine distance per-row at query time (see above) — no
  spatial index is possible without changing the Ride table schema.
- `rider_email` filtering is exact-match (case-insensitive); a partial-match option could
  be added with `lookup_expr="icontains"` if that's the desired UX.
- Token issuance uses a throttled wrapper around DRF's `obtain_auth_token`; a production
  system would likely want short-lived tokens with refresh (e.g. `djangorestframework-simplejwt`)
  rather than DRF's non-expiring `Token` model.
