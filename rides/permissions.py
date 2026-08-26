import logging

from rest_framework.permissions import BasePermission

logger = logging.getLogger("rides.security")


class IsAdminRole(BasePermission):
    """Grants access only to authenticated users whose role is 'admin'.

    This is distinct from Django's built-in is_staff/is_superuser flags -
    it checks the domain-specific `role` field on the custom User model,
    as required by the assessment spec.
    """

    message = "Only users with the 'admin' role may access this endpoint."

    def has_permission(self, request, view):
        user = request.user
        granted = bool(
            user
            and user.is_authenticated
            and getattr(user, "role", None) == "admin"
        )
        # OWASP A09: log denied access attempts by authenticated non-admin
        # users so privilege-escalation attempts are visible after the fact.
        # (Anonymous requests are excluded - those are just normal 401s.)
        if not granted and user and user.is_authenticated:
            logger.warning(
                "Permission denied: user_id=%s role=%r attempted %s %s",
                user.pk, getattr(user, "role", None), request.method, request.path,
            )
        return granted
