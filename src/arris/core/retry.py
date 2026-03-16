"""Retry logic for flaky router operations."""

from __future__ import annotations

import functools
import logging
import time
from typing import Callable, TypeVar

from selenium.common.exceptions import (
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)

from .exceptions import LoginError, RouterTimeoutError, SessionExpiredError

log = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable)

RECOVERABLE = (
    TimeoutException,
    StaleElementReferenceException,
    WebDriverException,
    RouterTimeoutError,
    LoginError,
)


def retry(
    max_attempts: int = 3,
    delay: float = 3.0,
    backoff: float = 1.5,
    recoverable: tuple[type[Exception], ...] = RECOVERABLE,
) -> Callable[[F], F]:
    """Retry decorator with exponential backoff.

    Will not retry SessionExpiredError — that must be handled at a higher level.
    """

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            last_exc = None
            wait = delay
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except SessionExpiredError:
                    raise
                except recoverable as exc:
                    last_exc = exc
                    if attempt < max_attempts:
                        log.warning(
                            "%s attempt %d/%d failed: %s — retrying in %.1fs",
                            fn.__name__,
                            attempt,
                            max_attempts,
                            exc,
                            wait,
                        )
                        time.sleep(wait)
                        wait *= backoff
                    else:
                        log.error(
                            "%s failed after %d attempts: %s",
                            fn.__name__,
                            max_attempts,
                            exc,
                        )
            raise last_exc  # type: ignore[misc]

        return wrapper  # type: ignore[return-value]

    return decorator
