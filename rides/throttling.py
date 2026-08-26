from rest_framework.throttling import AnonRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    """Rate-limits the token-auth endpoint by client IP.

    OWASP A07 (Identification and Authentication Failures): without this,
    the login endpoint has no brute-force protection at all - the built-in
    DRF `ObtainAuthToken` view explicitly sets `throttle_classes = ()`,
    opting itself out of the global throttle settings.
    """

    scope = "login"
