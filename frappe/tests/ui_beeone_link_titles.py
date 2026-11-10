# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Browser test: a Link to a record with an opaque name (hash) shows its title, never the code.

It drives a running site with Playwright, so `bench run-tests` does not collect it. Run:

	BEEONE_UI_URL=http://localhost:8000 BEEONE_UI_PASSWORD=... pytest frappe/tests/ui_beeone_link_titles.py

It makes two custom doctypes (a hash-named catalog with a title field and no
`show_title_field_in_link`, and a document that links it) and removes them at the end.
Environment: BEEONE_UI_URL, BEEONE_UI_USER (default Administrator), BEEONE_UI_PASSWORD.
"""

import json
import os

import pytest

playwright = pytest.importorskip("playwright.sync_api")

URL = os.environ.get("BEEONE_UI_URL")
pytestmark = pytest.mark.skipif(not URL, reason="BEEONE_UI_URL is not set")

CATALOG = "T886 UI Catalog"
HOLDER = "T886 UI Holder"
TITLE = "Wholesale price T886"


def api(page, method, path, **kwargs):
	response = page.context.request.fetch(f"{URL}{path}", method=method, **kwargs)
	assert response.ok, response.text()
	return response.json()


def doctype(name, fields, **kwargs):
	return {
		"doctype": "DocType",
		"name": name,
		"module": "Core",
		"custom": 1,
		"fields": fields,
		"permissions": [{"role": "System Manager", "read": 1, "write": 1, "create": 1, "delete": 1}],
		**kwargs,
	}


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
		for name in (HOLDER, CATALOG):
			page.context.request.delete(f"{URL}/api/resource/DocType/{name}")
		browser.close()


@pytest.fixture(scope="module")
def data(page):
	api(
		page,
		"POST",
		"/api/resource/DocType",
		data=doctype(
			CATALOG,
			[{"fieldname": "thing_name", "fieldtype": "Data", "label": "Thing name", "reqd": 1}],
			autoname="hash",
			title_field="thing_name",
		),
	)
	api(
		page,
		"POST",
		"/api/resource/DocType",
		data=doctype(
			HOLDER,
			[
				{"fieldname": "caption", "fieldtype": "Data", "label": "Caption"},
				{"fieldname": "catalog", "fieldtype": "Link", "options": CATALOG, "label": "Catalog"},
			],
			autoname="field:caption",
		),
	)
	code = api(page, "POST", f"/api/resource/{CATALOG}", data={"thing_name": TITLE})["data"]["name"]
	api(page, "POST", f"/api/resource/{HOLDER}", data={"caption": "holder one", "catalog": code})
	return code


def open_form(page):
	page.goto(f"{URL}/desk/{HOLDER.lower().replace(' ', '-')}/holder%20one")
	page.wait_for_selector("[data-fieldname=catalog] input", state="attached", timeout=60000)
	page.wait_for_timeout(1500)


def test_field_shows_the_title(page, data):
	open_form(page)
	assert page.input_value("[data-fieldname=catalog] input") == TITLE


def test_dropdown_shows_the_title_without_the_code(page, data):
	open_form(page)
	field = "[data-fieldname=catalog] input"
	page.click(field)
	page.fill(field, "")
	page.type(field, "Wholesale", delay=80)
	page.wait_for_selector("[data-fieldname=catalog] .awesomplete li", timeout=15000)
	text = page.inner_text("[data-fieldname=catalog] .awesomplete ul")
	assert TITLE in text
	assert data not in text


def test_formatter_fills_the_title_for_a_value_not_in_the_cache(page, data):
	open_form(page)
	text = page.evaluate(
		"""async ([doctype, name]) => {
			const holder = document.createElement("div");
			holder.innerHTML = frappe.format(name, { fieldtype: "Link", options: doctype });
			document.body.appendChild(holder);
			await new Promise((resolve) => setTimeout(resolve, 1500));
			return holder.innerText;
		}""",
		[CATALOG, data],
	)
	assert text == TITLE


def test_filter_from_the_route_shows_the_title(page, data):
	page.goto(f"{URL}/desk/{HOLDER.lower().replace(' ', '-')}?catalog={data}")
	page.wait_for_selector(".filter-button", timeout=60000)
	page.click(".filter-button")
	page.wait_for_timeout(1500)
	values = json.dumps(
		page.evaluate("[...document.querySelectorAll('.filter-popover input')].map((e) => e.value)")
	)
	assert TITLE in values
	assert data not in values
