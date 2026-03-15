"""Base page object for all router pages."""

from __future__ import annotations

import logging

from ..core.forms import FormHelper
from ..core.session import RouterSession
from ..core.tables import TableHelper

log = logging.getLogger(__name__)


class BasePage:
    """Base class for router page objects.

    Subclasses must set PAGE_MID to the mid parameter value for navigation
    (e.g. "NetPortMapping" for Port-Forwarding). This is mode-independent —
    it works in both Standard and Expert modes regardless of nav item numbering.
    """

    PAGE_MID: str = ""

    def __init__(self, session: RouterSession):
        self._session = session
        self._forms = FormHelper(session)
        self._tables = TableHelper(session)

    def navigate(self) -> None:
        """Navigate to this page."""
        if not self.PAGE_MID:
            raise NotImplementedError("PAGE_MID must be set")
        self._session.navigate(self.PAGE_MID)

    def apply(self) -> None:
        """Click the page-level Apply button."""
        self._session.apply()

    def _navigate_fresh(self) -> None:
        """Navigate to the page again (useful after apply to refresh state)."""
        self.navigate()
