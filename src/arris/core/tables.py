"""Table reading and row operations for the ARRIS router."""

from __future__ import annotations

import logging
from typing import Any

from .session import RouterSession
from .waits import settle

log = logging.getLogger(__name__)


class TableHelper:
    """Read and manipulate HTML tables on router pages."""

    def __init__(self, session: RouterSession):
        self._session = session

    def read_table(
        self, *, row_selector: str = "table tr", min_columns: int = 2
    ) -> list[list[str]]:
        """Read all table rows as lists of cell text."""
        return self._session.execute(
            """
            var rows = document.querySelectorAll(arguments[0]);
            var result = [];
            for (var r = 0; r < rows.length; r++) {
                var tds = rows[r].querySelectorAll("td");
                if (tds.length >= arguments[1]) {
                    var cells = [];
                    for (var c = 0; c < tds.length; c++)
                        cells.push(tds[c].textContent.trim());
                    result.push(cells);
                }
            }
            return result;
            """,
            row_selector,
            min_columns,
        )

    def read_table_dicts(
        self,
        *,
        row_selector: str = "table tr",
        headers: list[str] | None = None,
        min_columns: int = 2,
    ) -> list[dict[str, str]]:
        """Read table rows as dicts keyed by header names.

        If headers is None, uses the first row as headers.
        """
        rows = self.read_table(
            row_selector=row_selector, min_columns=min_columns
        )
        if not rows:
            return []

        if headers is None:
            # Try reading <th> elements
            th_headers = self._session.execute(
                """
                var ths = document.querySelectorAll(arguments[0] + " th");
                if (ths.length === 0) {
                    var firstRow = document.querySelector(arguments[0]);
                    ths = firstRow ? firstRow.querySelectorAll("th, td") : [];
                }
                return Array.from(ths).map(function(th) {
                    return th.textContent.trim();
                });
                """,
                row_selector,
            )
            if th_headers:
                headers = th_headers

        if headers:
            return [
                {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
                for row in rows
                if any(cell.strip() for cell in row[:min_columns])
            ]
        return [{"col_" + str(i): cell for i, cell in enumerate(row)} for row in rows]

    def click_row_button(
        self,
        *,
        row_match: dict[str, str],
        button_class: str,
        row_selector: str = "table tr",
    ) -> bool:
        """Find a row matching column values and click a button within it.

        Args:
            row_match: Dict of {column_text: expected_value} to identify the row.
            button_class: CSS class of the button, e.g. "button-edit" or "button-delete".
            row_selector: CSS selector for table rows.

        Returns:
            True if found and clicked, False otherwise.
        """
        match_values = list(row_match.values())
        return self._session.execute(
            """
            var matchValues = arguments[0];
            var btnClass = arguments[1];
            var rows = document.querySelectorAll(arguments[2]);
            for (var r = 0; r < rows.length; r++) {
                var tds = rows[r].querySelectorAll("td");
                var texts = [];
                for (var c = 0; c < tds.length; c++)
                    texts.push(tds[c].textContent.trim());

                var allMatch = true;
                for (var m = 0; m < matchValues.length; m++) {
                    if (texts.indexOf(matchValues[m]) === -1) {
                        allMatch = false;
                        break;
                    }
                }
                if (allMatch) {
                    var btn = rows[r].querySelector("." + btnClass);
                    if (btn) { btn.click(); return true; }
                }
            }
            return false;
            """,
            match_values,
            button_class,
            row_selector,
        )

    def delete_all_rows(self, *, row_selector: str = "table tr") -> int:
        """Delete every row by clicking delete buttons until none remain."""
        deleted = 0
        while True:
            found = self._session.execute(
                """
                var rows = document.querySelectorAll(arguments[0]);
                for (var r = 0; r < rows.length; r++) {
                    var btn = rows[r].querySelector(".button-delete");
                    if (btn && btn.getBoundingClientRect().height > 0) {
                        btn.click();
                        return true;
                    }
                }
                return false;
                """,
                row_selector,
            )
            if not found:
                break
            deleted += 1
            settle(1.5)
        return deleted

    def count_rows(self, *, row_selector: str = "table tr", min_columns: int = 2) -> int:
        """Count the number of data rows in a table."""
        return self._session.execute(
            """
            var rows = document.querySelectorAll(arguments[0]);
            var count = 0;
            for (var r = 0; r < rows.length; r++) {
                var tds = rows[r].querySelectorAll("td");
                if (tds.length >= arguments[1]) {
                    var hasContent = false;
                    for (var c = 0; c < tds.length; c++) {
                        if (tds[c].textContent.trim().indexOf(":") > 0) {
                            hasContent = true; break;
                        }
                    }
                    if (hasContent) count++;
                }
            }
            return count;
            """,
            row_selector,
            min_columns,
        )
