"""Exception hierarchy for router operations."""


class ArrisError(Exception):
    """Base exception for all arris-router errors."""


class LoginError(ArrisError):
    """Failed to authenticate with the router."""


class NavigationError(ArrisError):
    """Failed to navigate to a router page."""


class FormError(ArrisError):
    """Failed to interact with a form element."""


class PopupError(FormError):
    """Popup did not open or close as expected."""


class ApplyError(ArrisError):
    """Router rejected or failed to apply a configuration change."""


class SessionExpiredError(ArrisError):
    """Router session timed out, need to re-login."""


class RouterTimeoutError(ArrisError):
    """Router did not respond within the expected time."""
