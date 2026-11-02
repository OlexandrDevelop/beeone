"""pytest building blocks: users per role, the site-up guard, the browser. Applications declare the fixtures."""
import requests

from .values import uid


def make_user(admin, roles, prefix, password, language="en"):
    """Create a system user with the roles through the public API and return its e-mail."""
    email = f"bb-{prefix}-{uid()}@example.com"
    admin.insert(
        "User", email=email, first_name=f"BB {prefix}", send_welcome_email=0, user_type="System User",
        language=language, new_password=password, roles=[{"role": r} for r in roles],
    )
    return email


def site_reachable(base, timeout=10):
    try:
        return requests.get(base + "/api/method/ping", timeout=timeout).status_code == 200
    except Exception:
        return False


def browser_session():
    """Generator for a session-scoped `browser` fixture (Playwright Chromium)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()
