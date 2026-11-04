from rest_framework.permissions import SAFE_METHODS, BasePermission


def is_admin(user) -> bool:
    """Role `admin` = Django `is_staff`; everyone else is a read-only user."""
    return bool(user and user.is_authenticated and user.is_staff)


class IsAdminOrReadOnly(BasePermission):
    """Default for every API view: users read (safe methods), admins all."""

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return request.method in SAFE_METHODS or is_admin(request.user)


class IsAdmin(BasePermission):
    """Admin-only views, including GETs with side effects (live reads)."""

    def has_permission(self, request, view):
        return is_admin(request.user)
