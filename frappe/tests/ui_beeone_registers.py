# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Browser test of the movement viewer and the register lists.

It drives a running site with Playwright, so `bench run-tests` does not collect it. Run:

	bench --site <site> execute frappe.tests.beeone_register_fixtures.create
	BEEONE_UI_URL=http://localhost:8000 BEEONE_UI_PASSWORD=... pytest frappe/tests/ui_beeone_registers.py

Environment: BEEONE_UI_URL, BEEONE_UI_USER (default Administrator), BEEONE_UI_PASSWORD,
BEEONE_UI_SHOTS (folder for screenshots, optional), BEEONE_UI_LABELS (JSON map from an
English command text to the text the site shows, for a translated desk).
"""

import json
import os
import re
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")

URL = os.environ.get("BEEONE_UI_URL")
pytestmark = pytest.mark.skipif(not URL, reason="BEEONE_UI_URL is not set")

LABELS = json.loads(os.environ.get("BEEONE_UI_LABELS") or "{}")
SHOTS = os.environ.get("BEEONE_UI_SHOTS")
LEDGER = "beeone-move-ledger"
DOCUMENT = "beeone-move-document"


def label(text):
	return LABELS.get(text, text)


def shot(page, name):
	if SHOTS:
		Path(SHOTS).mkdir(parents=True, exist_ok=True)
		page.wait_for_timeout(600)  # let the dialog finish its animation
		page.screenshot(path=str(Path(SHOTS) / f"{name}.png"))


@pytest.fixture(scope="module")
def page():
	with playwright.sync_playwright() as p:
		browser = p.chromium.launch()
		context = browser.new_context(viewport={"width": 1440, "height": 900}, locale="en-US")
		response = context.request.post(
			f"{URL}/api/method/login",
			form={
				"usr": os.environ.get("BEEONE_UI_USER", "Administrator"),
				"pwd": os.environ["BEEONE_UI_PASSWORD"],
			},
		)
		assert response.ok, response.text()
		page = context.new_page()
		yield page
		browser.close()


@pytest.fixture(scope="module")
def document(page):
	names = page.context.request.get(
		f"{URL}/api/resource/Beeone Move Document",
		params={"filters": json.dumps([["docstatus", "=", 1]]), "limit_page_length": 1},
	).json()["data"]
	assert names, "run frappe.tests.beeone_register_fixtures.create first"
	return names[0]["name"]


def open_desk(page, route):
	page.goto(f"{URL}/desk/{route}")
	page.wait_for_function("window.frappe && frappe.boot && frappe.boot.beeone_registers")


def test_movements_button_shows_one_tab_per_register_with_rows(page, document):
	open_desk(page, f"{DOCUMENT}/{document}")
	button = page.get_by_role("button", name=label("Document Movements"), exact=True)
	button.wait_for()
	shot(page, "form")
	button.click()
	dialog = page.locator(".modal.show .beeone-viewer")
	dialog.wait_for()
	tabs = dialog.locator(".beeone-tab")
	assert tabs.count() == 1  # the second register has no rows for the document
	assert "3" in tabs.first.inner_text()
	assert dialog.locator(".beeone-panel tbody tr").count() == 3
	totals = dialog.locator(".beeone-panel tfoot").inner_text()
	assert "17" in totals and "340" in totals
	shot(page, "movements")


def test_draft_document_has_no_movements_button(page):
	open_desk(page, f"{DOCUMENT}/new")
	page.wait_for_selector(".page-actions")
	assert page.get_by_role("button", name=label("Document Movements"), exact=True).count() == 0


def test_register_list_is_read_only(page):
	open_desk(page, LEDGER)
	page.wait_for_selector(".list-row")
	assert page.locator(".primary-action:visible").count() == 0
	assert page.get_by_role("button", name=label("Balance"), exact=True).count() == 1
	assert page.get_by_role("button", name=label("Turnovers"), exact=True).count() == 1
	shot(page, "list")


def test_register_row_form_is_read_only(page):
	open_desk(page, LEDGER)
	page.wait_for_selector(".list-row")
	page.locator(".list-row .level-left a").first.click()
	page.wait_for_selector(".form-layout")
	assert page.locator(".primary-action:visible").count() == 0
	assert page.locator(".form-layout input:not([disabled]):not([readonly]):visible").count() == 0


def test_balance_command(page):
	open_desk(page, LEDGER)
	page.wait_for_selector(".list-row")
	page.get_by_role("button", name=label("Balance"), exact=True).click()
	result = page.locator(".modal.show .beeone-viewer .beeone-table")
	result.wait_for()
	assert result.locator("tbody tr").count() == 3
	shot(page, "balance")


def test_turnover_command(page):
	open_desk(page, LEDGER)
	page.wait_for_selector(".list-row")
	page.get_by_role("button", name=label("Turnovers"), exact=True).click()
	page.wait_for_selector(".modal.show .beeone-viewer")
	top = "beeone.registers.report_form"
	page.evaluate(f"{top}.set_value('start', '2026-03-01')")
	page.evaluate(f"{top}.set_value('end', '2026-03-31')")
	page.locator('.modal.show input[data-unit="item"]').uncheck()
	page.locator(".modal.show .btn-modal-primary").click()
	page.wait_for_function("document.querySelectorAll('.modal.show .beeone-table tbody tr').length === 2")
	shot(page, "turnover")
