"""Expectations on failing calls."""
from .api import ApiError


def expect_error(fn, text, *args, **kwargs):
    """Run fn: a business error (HTTP 417) whose message contains `text` is required."""
    try:
        fn(*args, **kwargs)
    except ApiError as e:
        assert e.status == 417 or "ValidationError" in e.exc_type, f"not a business error: {e}"
        assert text in e.message, f"expected «{text}» in the error, got: {e.message[:500]}"
        return e
    raise AssertionError(f"expected an error with «{text}», but the call succeeded")


def expect_denied(fn, *args, **kwargs):
    """Run fn: a permission error (HTTP 403 / PermissionError) is required."""
    try:
        fn(*args, **kwargs)
    except ApiError as e:
        assert e.status == 403 or "PermissionError" in e.exc_type, f"not a permission error: {e}"
        return e
    raise AssertionError("expected a permission error, but the call succeeded")
