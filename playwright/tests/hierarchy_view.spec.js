import { test, expect } from "../support";

const DT = "Custom Catalog";
const URL = "/desk/custom-catalog";

const rows = (page) => page.locator(".result-container .list-row-container[data-name]");
const tree_row = (page, name) =>
	page.locator('.group-tree-row[role="treeitem"]').filter({ hasText: new RegExp(`^\\s*${name}\\s*$`) });

async function open_view(page, desk, url = URL) {
	await page.goto(url);
	await desk.ready();
	// a fresh site offers its welcome dialog once
	const later = page.getByText("Decide later");
	if (await later.isVisible().catch(() => false)) await later.click();
	await expect(rows(page).first()).toBeVisible();
}

test.describe("Hierarchy view", () => {
	test.beforeAll(async ({ admin }) => {
		await admin.call("frappe.tests.ui_test_helpers.setup_hierarchy_doctype");
	});

	test.beforeEach(async ({ page, api }) => {
		// every test starts at the top level, whatever the previous one saved
		await page.goto("/desk");
		await page.waitForFunction(() => window.frappe && frappe.csrf_token);
		await api.call("frappe.model.utils.user_settings.save", {
			doctype: DT,
			user_settings: JSON.stringify({ Hierarchy: { current_group: "" } }),
		});
	});

	test("opens by default with groups first and only groups in the tree", async ({
		page,
		desk,
	}) => {
		await open_view(page, desk);
		expect(await page.evaluate(() => cur_list.view_name)).toBe("Hierarchy");

		const flags = await rows(page).evaluateAll((els) => els.map((e) => e.dataset.isGroup));
		expect(flags).toEqual(["1", "1", "0", "0", "0"]);
		await expect(rows(page).first().locator(".hierarchy-group-icon svg")).toBeVisible();

		// the top level, Group A and Group B: no items, and A1 only after A is expanded
		await expect(page.locator(".group-tree-row")).toHaveCount(3);
		await expect(tree_row(page, "Group A")).toBeVisible();
		await expect(tree_row(page, "Group B")).toBeVisible();
		await expect(tree_row(page, "Group A1")).toBeHidden();
	});

	test("selecting a group in the tree shows its content, groups first, loads lazily", async ({
		page,
		desk,
	}) => {
		await open_view(page, desk);
		await tree_row(page, "Group A").click();
		await expect(rows(page).first()).toHaveAttribute("data-name", "Group A1");
		await expect(rows(page).first()).toHaveAttribute("data-is-group", "1");
		await expect(page.locator(".list-count")).toContainText("251");
		const first_page = await page.evaluate(() => cur_list.data.length);
		expect(first_page).toBeLessThan(251);
		await page.evaluate(() => {
			const c = document.querySelector(".result-container");
			c.scrollTop = c.scrollHeight;
		});
		await expect
			.poll(() => page.evaluate(() => cur_list.data.length), { timeout: 20000 })
			.toBeGreaterThan(first_page);
	});

	test("double click on a group drills in and syncs the tree; Ctrl+Up goes back", async ({
		page,
		desk,
	}) => {
		await open_view(page, desk);
		await tree_row(page, "Group A").click();
		await expect(rows(page).first()).toHaveAttribute("data-name", "Group A1");
		await rows(page).first().dblclick();
		await expect(tree_row(page, "Group A1")).toHaveAttribute("aria-selected", "true");
		await expect(tree_row(page, "Group A1")).toBeVisible();
		await expect(page.locator(".hierarchy-crumb")).toHaveText([
			"Custom Catalog",
			"Group A",
			"Group A1",
		]);
		await expect(rows(page)).toHaveCount(2);
		await page.keyboard.press("Control+ArrowUp");
		await expect(tree_row(page, "Group A")).toHaveAttribute("aria-selected", "true");
		await expect(rows(page).first()).toHaveAttribute("data-name", "Group A1");
	});

	test("double click on an item opens its form", async ({ page, desk }) => {
		await open_view(page, desk);
		await rows(page).filter({ hasText: "Top item 1" }).dblclick();
		await expect(page).toHaveURL(/custom-catalog\/Top(%20|\+| )item(%20|\+| )1/);
	});

	test("new item and new group are created in the current group", async ({ page, desk }) => {
		await open_view(page, desk);
		await tree_row(page, "Group A").click();
		await expect(rows(page).first()).toHaveAttribute("data-name", "Group A1");
		await page.locator(".primary-action").first().click();
		await expect(page).toHaveURL(/new-custom-catalog/);
		await expect
			.poll(() =>
				page.evaluate(() => [cur_frm.doc.parent_custom_catalog, cur_frm.doc.is_group])
			)
			.toEqual(["Group A", 0]);

		await page.goBack();
		await expect(rows(page).first()).toBeVisible();
		await page.getByRole("button", { name: "Add Group" }).click();
		await expect
			.poll(() =>
				page.evaluate(() => [cur_frm.doc.parent_custom_catalog, cur_frm.doc.is_group])
			)
			.toEqual(["Group A", 1]);
	});

	test("sorting keeps the groups first", async ({ page, desk }) => {
		await open_view(page, desk);
		await tree_row(page, "Group A").click();
		await expect(rows(page).first()).toHaveAttribute("data-name", "Group A1");
		await page.evaluate(() => {
			cur_list.sort_selector.set_value("title", "desc");
			cur_list.on_sort_change("title", "desc");
		});
		await expect(rows(page).first()).toHaveAttribute("data-name", "Group A1");
		await expect(rows(page).nth(1)).toHaveAttribute("data-name", "A item 250");
	});

	test("a filter searches the subtree and shows the scope line", async ({ page, desk }) => {
		await open_view(page, desk);
		await tree_row(page, "Group A").click();
		await expect(rows(page).first()).toHaveAttribute("data-name", "Group A1");
		await page.evaluate(() => cur_list.filter_area.add([["Custom Catalog", "title", "like", "%A1 item%"]]));
		await expect(rows(page).first()).toHaveAttribute("data-name", "A1 item 1");
		await expect(page.locator(".hierarchy-scope")).toBeVisible();
		await page.locator(".hierarchy-scope-clear").click();
		await expect(page.locator(".hierarchy-scope")).toBeHidden();
		await expect(rows(page).first()).toHaveAttribute("data-name", "Group A1");
	});

	test("keyboard only: tree, table, Enter and F2", async ({ page, desk }) => {
		await open_view(page, desk);
		await tree_row(page, "Custom Catalog").focus();
		await page.keyboard.press("ArrowDown");
		await expect(tree_row(page, "Group A")).toBeFocused();
		await page.keyboard.press("ArrowRight");
		await expect(tree_row(page, "Group A")).toHaveAttribute("aria-expanded", "true");
		await page.keyboard.press("ArrowLeft");
		await expect(tree_row(page, "Group A")).toHaveAttribute("aria-expanded", "false");
		await page.keyboard.press("Enter");
		await expect(tree_row(page, "Group A")).toHaveAttribute("aria-selected", "true");
		await expect(rows(page).first()).toHaveAttribute("data-name", "Group A1");

		await rows(page).first().focus();
		await page.keyboard.press("Enter");
		await expect(page.locator(".hierarchy-crumb[aria-current='location']")).toHaveText("Group A1");
		await expect(rows(page).first()).toBeFocused();
		await page.keyboard.press("F2");
		await expect(page).toHaveURL(/custom-catalog\/Group(%20|\+| )A1/);
	});

	test("move checked items to another group", async ({ page, desk }) => {
		await open_view(page, desk);
		await page.evaluate(() => cur_list.open_group("Group A1"));
		await expect(rows(page).first()).toHaveAttribute("data-name", "A1 item 1");
		await rows(page).first().locator(".list-row-checkbox").check();
		await desk.click_action_button("Move to Group…");
		const dialog = page.locator(".modal.show");
		await page.evaluate(() => cur_dialog.set_value("group", "Group B"));
		await dialog.getByRole("button", { name: "Move" }).click();
		await expect
			.poll(async () => (await page.evaluate(() => cur_list.data.map((d) => d.name))).join())
			.toBe("A1 item 2");
		await page.evaluate(() => cur_list.open_group("Group B"));
		await expect(rows(page).first()).toHaveAttribute("data-name", "A1 item 1");
	});

	test("the classic tree and the view switcher still work", async ({ page, desk }) => {
		await page.goto(URL + "/view/tree");
		await desk.ready();
		await expect(page.locator(".tree-view-body")).toBeVisible();
		await page.goto(URL + "/view/hierarchy");
		await desk.ready();
		await expect(rows(page).first()).toBeVisible();
		expect(
			await page.evaluate(() => Object.keys(frappe.views.get_view_label_map()).includes("Hierarchy"))
		).toBeTruthy();
	});

	test("the tree and the table expose the ARIA structure", async ({ page, desk }) => {
		await open_view(page, desk);
		await expect(page.locator('ul[role="tree"][aria-label]')).toHaveCount(1);
		await expect(page.locator('nav.hierarchy-path[aria-label]')).toHaveCount(1);
		// exactly one row of the tree is in the tab order
		await expect(page.locator('.group-tree-row[tabindex="0"]')).toHaveCount(1);
	});
});
