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
from django.db.models import ExpressionWrapper, F, FloatField, Value
from django.db.models.functions import ATan2, Cos, Power, Radians, Sin, Sqrt

EARTH_RADIUS_KM = 6371.0


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
