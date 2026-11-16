# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Browser test (T-1112): switching between open shell windows makes no list/report data requests.

It drives a running site with Playwright, so `bench run-tests` does not collect it. Run:

	BEEONE_UI_URL=http://localhost:8000 BEEONE_UI_PASSWORD=... pytest frappe/tests/ui_beeone_t1111_focus_requests.py

Opens a list window (ToDo) and a report window (Permitted Documents For User), then activates them alternately three
times through the shell (beeone.shell.windows.focus, what a task bar click calls) and records the network.
Environment: BEEONE_UI_URL, BEEONE_UI_USER (default Administrator), BEEONE_UI_PASSWORD, BEEONE_UI_LIST_ROUTE and
BEEONE_UI_REPORT_ROUTE (slash-separated, to test HiveBooks "List/Надходження товарів та послуг/List" and the ОСВ report).
"""

import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")

URL = os.environ.get("BEEONE_UI_URL")
pytestmark = pytest.mark.skipif(not URL, reason="BEEONE_UI_URL is not set")

LIST_ROUTE = os.environ.get("BEEONE_UI_LIST_ROUTE", "List/ToDo/List").split("/")
REPORT_ROUTE = os.environ.get("BEEONE_UI_REPORT_ROUTE", "query-report/Permitted Documents For User").split("/")
DATA_CALLS = (
	"frappe.desk.reportview.get_count",
	"frappe.desk.reportview.get_list",
	"frappe.desk.reportview.get",
	"frappe.desk.query_report.run",
)


@pytest.fixture(scope="module")
def page():
	with playwright.sync_playwright() as p:
		browser = p.chromium.launch()
		context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")
		response = context.request.post(
			f"{URL}/api/method/login",
			form={"usr": os.environ.get("BEEONE_UI_USER", "Administrator"), "pwd": os.environ["BEEONE_UI_PASSWORD"]},
		)
		assert response.ok, response.text()
		page = context.new_page()
		page.goto(f"{URL}/desk")
		page.wait_for_function("window.beeone && beeone.shell && beeone.shell.active")
		yield page
		browser.close()


def open_window(page, route):
	page.evaluate("(r) => frappe.set_route(...r)", route)
	page.wait_for_function("(r) => frappe.get_route().join('/') === r.join('/')", arg=route)
	page.wait_for_load_state("networkidle")


def window_key(page, route):
	return page.evaluate(
		"(r) => beeone.shell.windows.route_key(r)", route
	)


def data_requests(requests):
	return [u for u in requests if any(name in u for name in DATA_CALLS)]


def test_switching_between_open_windows_does_not_reload_them(page):
	open_window(page, LIST_ROUTE)
	open_window(page, REPORT_ROUTE)
	keys = [window_key(page, LIST_ROUTE), window_key(page, REPORT_ROUTE)]

	requests = []
	page.on("request", lambda r: requests.append(r.url))
	for _ in range(3):
		for key in keys:
			page.evaluate("(k) => beeone.shell.windows.focus(k)", key)
			page.wait_for_function("(k) => beeone.shell.windows.wins.active === k", arg=key)
			page.wait_for_load_state("networkidle")
			assert page.evaluate("() => !!frappe.get_route().length")
			# no skeleton is painted for an already rendered window
			assert page.locator(".bo-win.is-active .list-skeleton, .bo-win.is-active .skeleton").count() == 0

	assert data_requests(requests) == [], data_requests(requests)
	assert page.evaluate("() => beeone.shell.windows.wins.syncing") is False


def test_refresh_and_first_open_still_load(page):
	requests = []
	page.on("request", lambda r: requests.append(r.url))
	open_window(page, LIST_ROUTE)
	page.evaluate("() => cur_list.refresh()")
	page.wait_for_load_state("networkidle")
	assert any("frappe.desk.reportview.get" in u for u in requests), requests
