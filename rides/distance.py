"""Database-side great-circle distance calculation.

Sorting a very large Ride table by "distance from a given point" must not
pull every row into Python just to sort it there. Instead we annotate the
queryset with a `distance` expression built from ORM math functions
(Radians/Sin/Cos/ATan2/Sqrt/Power) so the Haversine formula is evaluated and
ordered entirely by the database engine - the same query plan Django uses
for any other `order_by()`.

This works unmodified on SQLite, PostgreSQL and MySQL because Django ships
SQL implementations of these math functions for every supported backend.

Caveat: because `pickup_latitude`/`pickup_longitude` are plain FLOAT columns
(per the fixed table schema), the database cannot use a spatial index to
satisfy this ordering - it still has to compute the expression per row. For
a very large table in production, the recommended upgrade is a PostGIS
`PointField` with a GiST index, which lets `order_by('distance')` use the
`<->` KNN operator instead of a full computed sort. That would require
changing the Ride table schema, which is out of scope here.
"""
import math

from django.db.models import ExpressionWrapper, F, FloatField, Value
from django.db.models.functions import ATan2, Cos, Power, Radians, Sin, Sqrt

EARTH_RADIUS_KM = 6371.0


class InvalidCoordinateError(ValueError):
    """Raised when a client-supplied latitude/longitude fails validation."""


def parse_coordinate(raw_value: str, *, bound: float, field_name: str) -> float:
    """Parse and validate a single coordinate value from a query parameter.

    OWASP A03 (Injection) / A04 (Insecure Design): user input is never
    interpolated into SQL (it's bound via a parameterized `Value()`
    expression - see `annotate_distance` below), but it must still be
    validated as a sane, finite number before being handed to the database.
    Plain `float()` happily accepts `"nan"`, `"inf"`, and `"-inf"`, any of
    which would silently corrupt every row's computed distance/ordering.
    """
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        raise InvalidCoordinateError(f"{field_name} must be a valid number.")

    if not math.isfinite(value):
        raise InvalidCoordinateError(f"{field_name} must be a finite number.")

    if not -bound <= value <= bound:
        raise InvalidCoordinateError(f"{field_name} must be between -{bound} and {bound}.")

    return value


def annotate_distance(queryset, latitude: float, longitude: float, field_prefix: str = "pickup"):
    """Annotate `queryset` with a `distance` field (km) from (latitude, longitude).

    Computed with the Haversine formula, entirely via database expressions.
    """
    lat_field = f"{field_prefix}_latitude"
    lon_field = f"{field_prefix}_longitude"

    lat1 = Radians(F(lat_field))
    lon1 = Radians(F(lon_field))
    lat2 = Radians(Value(latitude, output_field=FloatField()))
    lon2 = Radians(Value(longitude, output_field=FloatField()))

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = Power(Sin(dlat / 2.0), 2) + Cos(lat1) * Cos(lat2) * Power(Sin(dlon / 2.0), 2)
    c = 2 * ATan2(Sqrt(a), Sqrt(1 - a))

    distance_km = ExpressionWrapper(EARTH_RADIUS_KM * c, output_field=FloatField())
    return queryset.annotate(distance=distance_km)
