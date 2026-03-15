"""Form interaction helpers for the ARRIS router SPA.

Handles jQuery Chosen dropdowns, popup overlays, and flaky inputs.
All selectors use element IDs or structural CSS — never language-dependent text.
"""

from __future__ import annotations

import logging

from selenium.webdriver.support.ui import WebDriverWait

from .exceptions import FormError, PopupError
from .session import RouterSession
from .waits import ElementHidden, ElementVisible, settle

log = logging.getLogger(__name__)


class FormHelper:
    """Interact with form elements on the ARRIS router."""

    def __init__(self, session: RouterSession):
        self._session = session

    def set_input(self, element_id: str, value: str) -> None:
        """Set a text input's value by ID, with verification."""
        self._session.execute(
            """
            var el = document.getElementById(arguments[0]);
            if (!el) throw new Error('Input not found: ' + arguments[0]);
            el.value = arguments[1];
            el.dispatchEvent(new Event('change', {bubbles: true}));
            """,
            element_id,
            value,
        )
        actual = self._session.execute(
            "return document.getElementById(arguments[0]).value;", element_id
        )
        if actual != value:
            raise FormError(
                f"Input #{element_id}: expected {value!r}, got {actual!r}"
            )

    def set_input_by_js(self, selector: str, value: str) -> None:
        """Set an input value using a CSS selector."""
        self._session.execute(
            """
            var el = document.querySelector(arguments[0]);
            if (!el) throw new Error('Element not found: ' + arguments[0]);
            el.value = arguments[1];
            el.dispatchEvent(new Event('change', {bubbles: true}));
            """,
            selector,
            value,
        )

    def set_chosen_dropdown(self, select_id: str, value: str) -> None:
        """Set a jQuery Chosen dropdown's value.

        The real <select> is hidden; Chosen renders a custom widget.
        We set the value on the real select and trigger Chosen's update.
        """
        self._session.execute(
            """
            var sel = document.getElementById(arguments[0]);
            if (!sel) throw new Error('Select not found: ' + arguments[0]);
            sel.value = arguments[1];
            if (typeof jQuery !== 'undefined') {
                jQuery(sel).trigger('chosen:updated');
                jQuery(sel).trigger('change');
            } else {
                sel.dispatchEvent(new Event('change', {bubbles: true}));
            }
            """,
            select_id,
            value,
        )
        settle(0.5)
        actual = self._session.execute(
            "return document.getElementById(arguments[0]).value;", select_id
        )
        if str(actual) != str(value):
            log.warning(
                "Chosen #%s: set %r but read back %r", select_id, value, actual
            )

    def get_chosen_options(self, select_id: str) -> list[dict[str, str]]:
        """Get all options from a Chosen dropdown."""
        return self._session.execute(
            """
            var sel = document.getElementById(arguments[0]);
            if (!sel) return [];
            return Array.from(sel.options).map(function(o) {
                return {value: o.value, text: o.text};
            });
            """,
            select_id,
        )

    def click_radio(self, element_id: str) -> None:
        """Click a radio button by ID."""
        self._session.execute(
            """
            var el = document.getElementById(arguments[0]);
            if (el) { el.click(); el.dispatchEvent(new Event('change', {bubbles: true})); }
            """,
            element_id,
        )

    def click_button(self, element_id: str) -> None:
        """Click a button by ID."""
        self._session.execute(
            "document.getElementById(arguments[0]).click();", element_id
        )
        settle(1)

    def wait_popup_open(self, save_button_id: str, timeout: float = 15) -> None:
        """Wait for a popup to become visible by checking its save button."""
        try:
            WebDriverWait(self._session.driver, timeout).until(
                ElementVisible(save_button_id)
            )
        except Exception as exc:
            raise PopupError(f"Popup with #{save_button_id} did not open") from exc

    def wait_popup_close(self, save_button_id: str, timeout: float = 20) -> None:
        """Wait for a popup to close after save."""
        try:
            WebDriverWait(self._session.driver, timeout).until(
                ElementHidden(save_button_id)
            )
        except Exception as exc:
            raise PopupError(
                f"Popup with #{save_button_id} did not close — save may have failed"
            ) from exc

    def fill_mac_fields(self, mac: str) -> None:
        """Fill the 6 MAC address input fields in a visible popup.

        Uses multiple fallback strategies to find the fields:
        1. Class-based: input[class*='mac-address-input']
        2. MaxLength-based: input[type='text'][maxlength='2']
        3. Positional: last 10 visible inputs split as 6 MAC + 4 IP
        """
        parts = mac.upper().replace("-", ":").split(":")
        if len(parts) != 6:
            raise FormError(f"Invalid MAC address: {mac}")

        self._session.execute(
            """
            var parts = arguments[0];
            // Strategy 1: class-based
            var inputs = document.querySelectorAll("input[class*='mac-address-input']");
            var visible = [];
            for (var i = 0; i < inputs.length; i++)
                if (inputs[i].getBoundingClientRect().height > 0) visible.push(inputs[i]);

            if (visible.length < 6) {
                // Strategy 2: maxLength=2
                var all = document.querySelectorAll("input[type='text'][maxlength='2']");
                visible = [];
                for (var i = 0; i < all.length; i++)
                    if (all[i].getBoundingClientRect().height > 0) visible.push(all[i]);
            }

            if (visible.length < 6) {
                // Strategy 3: positional — look for groups of short inputs
                var allInputs = document.querySelectorAll("input[type='text']");
                var shortVisible = [];
                for (var i = 0; i < allInputs.length; i++) {
                    var inp = allInputs[i];
                    if (inp.getBoundingClientRect().height > 0 &&
                        (inp.maxLength <= 3 || inp.size <= 3)) {
                        shortVisible.push(inp);
                    }
                }
                // Take first 6 short inputs as MAC fields
                if (shortVisible.length >= 6) visible = shortVisible.slice(0, 6);
            }

            if (visible.length < 6)
                throw new Error('Found only ' + visible.length + ' MAC fields');
            for (var i = 0; i < 6; i++) {
                visible[i].value = parts[i];
                visible[i].dispatchEvent(new Event('change', {bubbles: true}));
            }
            """,
            parts,
        )

    def fill_ip_fields(self, ip: str) -> None:
        """Fill the 4 IP address input fields in a visible popup.

        Uses multiple fallback strategies:
        1. Class-based: input[class*='extra_ip_address']
        2. Class-based: input.max3 (last 4)
        3. Positional: last 4 visible maxLength=3 inputs
        """
        parts = ip.split(".")
        if len(parts) != 4:
            raise FormError(f"Invalid IP address: {ip}")

        self._session.execute(
            """
            var parts = arguments[0];
            // Strategy 1: class-based
            var inputs = document.querySelectorAll("input[class*='extra_ip_address']");
            var visible = [];
            for (var i = 0; i < inputs.length; i++)
                if (inputs[i].getBoundingClientRect().height > 0) visible.push(inputs[i]);

            if (visible.length < 4) {
                // Strategy 2: .max3 class
                var all = document.querySelectorAll("input.max3");
                visible = [];
                for (var i = 0; i < all.length; i++)
                    if (all[i].getBoundingClientRect().height > 0) visible.push(all[i]);
                visible = visible.slice(-4);
            }

            if (visible.length < 4) {
                // Strategy 3: positional — last 4 visible maxLength=3 inputs
                var allInputs = document.querySelectorAll("input[type='text'][maxlength='3']");
                var shortVisible = [];
                for (var i = 0; i < allInputs.length; i++) {
                    if (allInputs[i].getBoundingClientRect().height > 0)
                        shortVisible.push(allInputs[i]);
                }
                visible = shortVisible.slice(-4);
            }

            if (visible.length < 4)
                throw new Error('Found only ' + visible.length + ' IP fields');
            for (var i = 0; i < 4; i++) {
                visible[i].value = parts[i];
                visible[i].dispatchEvent(new Event('change', {bubbles: true}));
            }
            """,
            parts,
        )

    def fill_port_fields(
        self, wan_start: int, wan_end: int, lan_start: int, lan_end: int
    ) -> None:
        """Fill port forwarding fields, handling single vs range mode."""
        is_single = wan_start == wan_end and lan_start == lan_end

        if is_single:
            filled = self._session.execute(
                """
                var port = arguments[0];
                var pubS = document.getElementById("publicPortS");
                var locS = document.getElementById("localPortS");
                if (pubS && pubS.getBoundingClientRect().height > 0) {
                    pubS.value = port; locS.value = port;
                    return true;
                }
                return false;
                """,
                str(wan_start),
            )
            if filled:
                return

        # Range fields
        self._session.execute(
            """
            document.getElementById("publicPortR0").value = arguments[0];
            document.getElementById("publicPortR1").value = arguments[1];
            document.getElementById("privatePortR0").value = arguments[2];
            document.getElementById("privatePortR1").value = arguments[3];
            """,
            str(wan_start),
            str(wan_end),
            str(lan_start),
            str(lan_end),
        )

    def set_checkbox(self, element_id: str, checked: bool) -> None:
        """Set a checkbox state by ID."""
        self._session.execute(
            """
            var el = document.getElementById(arguments[0]);
            if (!el) throw new Error('Checkbox not found: ' + arguments[0]);
            if (el.checked !== arguments[1]) {
                el.click();
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }
            """,
            element_id,
            checked,
        )
