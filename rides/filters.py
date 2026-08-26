import django_filters

from .models import Ride


class RideFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(field_name="status", choices=Ride.Status.choices)
    rider_email = django_filters.CharFilter(field_name="rider__email", lookup_expr="iexact")

    class Meta:
        model = Ride
        fields = ["status", "rider_email"]
