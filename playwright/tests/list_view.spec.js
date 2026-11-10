import { test, expect } from "../support";

const CHECK_ALL = ".list-header-subject .list-subject .list-check-all";

test.describe("List View", () => {
	test.beforeAll(async ({ admin }) => {
		await admin.call("frappe.tests.ui_test_helpers.setup_workflow");
	});

	test.afterAll(async ({ admin }) => {
		await admin.remove_doc("Workflow", "Test ToDo", true);
	});

	test("Keep checkbox checked after Refresh", async ({ page, desk }) => {
		await desk.go_to_list("ToDo");
		await desk.clear_filters();
		await page.locator(CHECK_ALL).click();
		await page.locator("button[data-original-title='Reload List']").click();
		await expect(
			page.locator(".list-row-container .list-row-checkbox:checked").first()
		).toBeVisible();
	});

	test("keeps a Check '= No' standard filter applied", async ({ page, desk }) => {
		await desk.go_to_list("Web Page");
		await desk.clear_filters();
		await page.evaluate(() => {
			frappe.route_options = { published: ["=", 0] };
			frappe.set_route("List", "Web Page");
		});
		await expect(page.locator(".filter-selector .filter-button .button-label")).toContainText(
			"Filters"
		);
		await expect
			.poll(() =>
				page.evaluate(() =>
					cur_list.filter_area
						.get()
						.some((f) => f[1] === "published" && String(f[3]) === "0")
				)
			)
			.toBe(true);
	});

	test('enables "Actions" button', async ({ page, desk }) => {
		const actions = [
			"Approve",
			"Reject",
			"Copy to Clipboard",
			"Export",
			"Assign To",
			"Clear Assignment",
			"Apply Assignment Rule",
			"Add Tags",
			"Print",
		];
		await desk.go_to_list("ToDo");
		await desk.clear_filters();
		const common_actions = page.waitForResponse(
			(res) =>
				res.request().method() === "POST" &&
				res
					.url()
					.includes("/api/method/frappe.model.workflow.get_common_transition_actions")
		);
		await page.locator(CHECK_ALL).click();
		// selecting rows triggers the workflow-actions refresh (debounced);
		// wait for it to hide "Review" (not common to the selected docs)
		// before opening — the menu snapshots its items at open
		await common_actions;
		await expect(
			page
				.locator('.actions-btn-group [data-label="Review"]')
				.locator("xpath=ancestor::li[1]")
		).toHaveCSS("display", "none");
		await page.getByRole("button", { name: "Actions", exact: true }).click();

		const menu_items = page.locator('.es-menu [role="menuitem"]');
		await expect(menu_items).toHaveCount(9);
		for (const [index, action] of actions.entries()) {
			await expect(menu_items.nth(index)).toContainText(action);
		}

		const bulk_approval = page.waitForResponse(
			(res) =>
				res.request().method() === "POST" &&
				res.url().includes("api/method/frappe.model.workflow.bulk_workflow_approval")
		);
		await menu_items.filter({ hasText: "Approve" }).first().click();
		await bulk_approval;
		await desk.hide_dialog();
		await page.reload();
		await desk.clear_filters();
		await expect(
			page.locator(".list-row-container:visible", { hasText: "Approved" }).first()
		).toBeVisible();
	});

	test("Adds a button to each list view row", async ({ page, desk, api }) => {
		const r = await api.call("frappe.client.get_value", {
			doctype: "ToDo",
			filters: {
				reference_name: ["is", "set"],
			},
			fieldname: "name",
		});
		const todo_name = r.message.name;
		await desk.go_to_list("ToDo");

		const open_button = page.locator(`.btn-default[data-name="${todo_name}"]`);
		await open_button.scrollIntoViewIfNeeded();
		await expect(open_button).toBeVisible();
		await open_button.click();

		await expect.poll(() => page.evaluate(() => window.cur_frm?.doc.doctype)).toBe("ToDo");
		expect(await page.evaluate(() => cur_frm.doc.name)).not.toBe(todo_name);
	});

	test("translates field labels in the bulk edit dialog", async ({ page, desk, api }) => {
		const translations = {
			Route: "Routen-Pfad",
			"Web Page": "Webseite",
			"CSS Class": "CSS-Klasse",
			"Page Building Blocks": "Seitenbausteine",
		};

		await api.insert_doc(
			"Web Page",
			{ title: "Impressum", route: "impressum", content_type: "Rich Text" },
			true
		);
		await desk.go_to_list("Web Page");
		await desk.clear_filters();
		await page.locator(CHECK_ALL).click();

		await page.evaluate(
			(translations) => Object.assign(frappe._messages, translations),
			translations
		);
		await desk.click_action_button("Edit");

		const field = desk.get_open_dialog().locator('input[data-fieldname="field"]');
		const suggestions = page.locator(".awesomplete li:visible");

		await field.clear();
		await field.pressSequentially("Routen-Pfad");
		await expect(
			suggestions.filter({ hasText: "Routen-Pfad (Webseite)" }).first()
		).toBeVisible();

		await field.clear();
		await field.pressSequentially("CSS-Klasse");
		await expect(
			suggestions.filter({ hasText: "CSS-Klasse (Seitenbausteine)" }).first()
		).toBeVisible();

		await desk.hide_dialog();
		await api.remove_doc("Web Page", "impressum");
	});

	test("keeps selected rows checked after a list rerender", async ({ page, desk }) => {
		await desk.go_to_list("ToDo");
		await desk.clear_filters();

		await page.locator(".list-row-checkbox").first().click();

		const selected_docnames = await page.evaluate(() => Array.from(cur_list.checked_docnames));
		expect(selected_docnames.length).toBe(1);

		const selected_docname = selected_docnames[0];
		await page.evaluate(() => cur_list.render_list());

		await expect
			.poll(() =>
				page.evaluate((docname) => {
					const $checkbox = cur_list.find_checkbox_by_docname(docname);
					return { length: $checkbox.length, checked: $checkbox.prop("checked") };
				}, selected_docname)
			)
			.toEqual({ length: 1, checked: true });
	});

	test("preserves select-all across virtualized window rerenders", async ({ page, desk }) => {
		await desk.go_to_list("ToDo");
		await desk.clear_filters();

		const data_length = await page.evaluate(() => {
			cur_list.virtualization_threshold = 1;
			cur_list.render_list();
			return cur_list.data.length;
		});
		expect(data_length).toBeGreaterThan(0);

		await expect(
			page.locator('.list-row-container[data-virtual-row="1"]').first()
		).toBeAttached();
		await page.locator(CHECK_ALL).click();

		const all_checked = () =>
			page.evaluate(() => cur_list.checked_docnames.size === cur_list.data.length);
		expect(await all_checked()).toBe(true);

		await page.locator(".result-container").evaluate((el) => el.scrollTo(0, el.scrollHeight));
		await page.evaluate(() => cur_list.render_virtual_rows(true));

		expect(await all_checked()).toBe(true);

		await expect(
			page.locator(".result-container .list-row-checkbox:checked").first()
		).toBeAttached();
	});

	test.describe("scroll position of the virtual list", () => {
		test.beforeAll(async ({ admin }) => {
			const { message: count } = await admin.call("frappe.client.get_count", {
				doctype: "ToDo",
			});
			for (let i = count; i < 150; i++) {
				await admin.insert_doc("ToDo", { description: `T-882 scroll row ${i}` });
			}
		});

		async function open_virtual_list(page, desk) {
			await desk.go_to_list("ToDo");
			await page.waitForFunction(() => window.cur_list?.data?.length > 0);
			await page.evaluate(() => {
				cur_list.filter_area.clear();
				cur_list.virtualization_threshold = 1;
				cur_list.virtual_page_size = 20;
				cur_list.render_list();
			});
			await expect(
				page.locator('.list-row-container[data-virtual-row="1"]').first()
			).toBeAttached();
			// let the refresh caused by clearing the filters settle
			await page.waitForTimeout(1500);
		}

		const state = (page) =>
			page.evaluate(() => {
				const c = cur_list.$result.parent(".result-container")[0];
				return {
					top: c.scrollTop,
					length: cur_list.data.length,
					first: c.querySelector('.list-row-container[data-virtual-row="1"]')?.dataset
						.name,
				};
			});

		test("keeps the scroll position after auto-load", async ({ page, desk }) => {
			await open_virtual_list(page, desk);
			const before = await page.evaluate(async () => {
				const c = cur_list.$result.parent(".result-container")[0];
				const rows = cur_list.data.length;
				c.scrollTop = (c.scrollHeight / cur_list.get_virtual_total_rows()) * rows * 0.8;
				await new Promise((r) => setTimeout(r, 200));
				return { top: c.scrollTop, length: rows };
			});
			await expect.poll(async () => (await state(page)).length).toBeGreaterThan(before.length);
			await page.waitForTimeout(500);
			const after = await state(page);
			expect(before.top).toBeGreaterThan(0);
			expect(Math.abs(after.top - before.top)).toBeLessThan(3);
		});

		test("keeps the scroll position on refresh with the same query", async ({
			page,
			desk,
		}) => {
			await open_virtual_list(page, desk);
			await page.evaluate(() => {
				const c = cur_list.$result.parent(".result-container")[0];
				c.scrollTop = 300;
			});
			await page.waitForTimeout(300);
			const before = await state(page);
			await page.evaluate(() => {
				cur_list.last_args = null;
				return cur_list.refresh();
			});
			await page.waitForTimeout(500);
			const after = await state(page);
			expect(before.top).toBeGreaterThan(0);
			expect(Math.abs(after.top - before.top)).toBeLessThan(3);
			expect(after.first).toBe(before.first);
		});

		test("goes back to the top when the filter changes", async ({ page, desk }) => {
			await open_virtual_list(page, desk);
			await page.evaluate(() => {
				cur_list.$result.parent(".result-container")[0].scrollTop = 300;
			});
			await page.waitForTimeout(300);
			await page.evaluate(() => {
				cur_list.filter_area.add([["ToDo", "description", "like", "%T-882%"]]);
			});
			await page.waitForTimeout(1500);
			expect((await state(page)).top).toBe(0);
		});
	});

	test("keeps mobile virtual rows rendered during fast downward scroll", async ({
		page,
		desk,
	}) => {
		await page.setViewportSize({ width: 375, height: 667 });
		await desk.go_to_list("ToDo");
		await desk.clear_filters();

		const data_length = await page.evaluate(() => {
			cur_list.virtualization_threshold = 1;
			cur_list.render_list();
			return cur_list.data.length;
		});
		expect(data_length).toBeGreaterThan(0);

		await expect(
			page.locator('.list-row-container[data-virtual-row="1"]').first()
		).toBeAttached();

		await page.locator(".result-container").evaluate((el) => el.scrollTo(0, el.scrollHeight));
		await page.evaluate(() => cur_list.render_virtual_rows(true));

		await expect(
			page.locator('.list-row-container[data-virtual-row="1"] .list-row')
		).not.toHaveCount(0);

		const state = await page.evaluate(() => ({
			start: cur_list.virtualization_state.start,
			end: cur_list.virtualization_state.end,
		}));
		expect(state.end).toBeGreaterThan(state.start);
	});

	test("flips sort order icon and title", async ({ page, desk }) => {
		await desk.go_to_list("ToDo");
		await desk.clear_filters();

		await page.evaluate(() => {
			const sort_selector = cur_list.sort_selector;
			sort_selector.set_value(sort_selector.sort_by, "desc");
		});

		const order = page.locator(".sort-selector .btn-order");
		await expect(order).toHaveAttribute("title", "descending");
		await expect(order.locator(".sort-order use")).toHaveAttribute(
			"href",
			"#icon-arrow-down-wide-narrow"
		);

		await order.click();
		await expect(order).toHaveAttribute("data-value", "asc");
		await expect(order).toHaveAttribute("title", "ascending");
		await expect(order.locator(".sort-order use")).toHaveAttribute(
			"href",
			"#icon-arrow-up-narrow-wide"
		);
	});
});
