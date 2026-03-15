"""Tests for retry logic."""

import pytest
from unittest.mock import MagicMock

from arris.core.retry import retry
from arris.core.exceptions import SessionExpiredError, RouterTimeoutError


class TestRetry:
    def test_succeeds_first_try(self):
        call_count = 0

        @retry(max_attempts=3, delay=0.01)
        def fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert fn() == "ok"
        assert call_count == 1

    def test_succeeds_on_retry(self):
        call_count = 0

        @retry(max_attempts=3, delay=0.01)
        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RouterTimeoutError("timeout")
            return "ok"

        assert fn() == "ok"
        assert call_count == 3

    def test_raises_after_max_attempts(self):
        @retry(max_attempts=2, delay=0.01)
        def fn():
            raise RouterTimeoutError("timeout")

        with pytest.raises(RouterTimeoutError):
            fn()

    def test_does_not_retry_session_expired(self):
        call_count = 0

        @retry(max_attempts=3, delay=0.01)
        def fn():
            nonlocal call_count
            call_count += 1
            raise SessionExpiredError("expired")

        with pytest.raises(SessionExpiredError):
            fn()
        assert call_count == 1

    def test_does_not_retry_unrecoverable(self):
        call_count = 0

        @retry(max_attempts=3, delay=0.01, recoverable=(RouterTimeoutError,))
        def fn():
            nonlocal call_count
            call_count += 1
            raise ValueError("not recoverable")

        with pytest.raises(ValueError):
            fn()
        assert call_count == 1
