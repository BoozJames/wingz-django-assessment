from rest_framework.permissions import BasePermission


class IsAdminRole(BasePermission):
    """Grants access only to authenticated users whose role is 'admin'.

    This is distinct from Django's built-in is_staff/is_superuser flags -
    it checks the domain-specific `role` field on the custom User model,
    as required by the assessment spec.
    """

    message = "Only users with the 'admin' role may access this endpoint."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and getattr(user, "role", None) == "admin"
        )
