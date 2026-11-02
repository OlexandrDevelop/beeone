"""Country-neutral tooling of the black-box test suites that drive a running beeone site over HTTP.

The package is plain Python (requests, optionally playwright): it imports nothing from frappe, so a
host-side pytest run can load it straight from a beeone checkout (see README.md). Applications bring
their own rules, data and messages; nothing here knows a country, a chart of accounts or a language.
"""
from .api import Api, ApiError, FeatureMissing, Report  # noqa: F401
from .expect import expect_denied, expect_error  # noqa: F401
from .fixtures import browser_session, make_user, site_reachable  # noqa: F401
from .stack import Stack, read_env_file  # noqa: F401
from .values import add_days, make_tag, money, month_start, qty, today, uid, wait_until  # noqa: F401
