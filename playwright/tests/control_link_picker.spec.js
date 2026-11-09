import { test, expect } from "../support";

test.describe("Link field: select from list", () => {
	let stamp;
	let todos;
	let created = [];

	test.beforeEach(async ({ page, desk, api }) => {
		stamp = String(Date.now());
		todos = await api.create_records([
			{ doctype: "ToDo", description: `picker alpha ${stamp}` },
			{ doctype: "ToDo", description: `picker beta ${stamp}` },
			{ doctype: "ToDo", description: `other ${stamp}` },
		]);
		created = [...todos];
		await page.goto("/desk/todo");
		await desk.ready();
		const later = page.getByText("Decide later");
		if (await later.isVisible()) await later.click();
	});

	test.afterEach(async ({ admin }) => {
		for (const name of created) {
			await admin.remove_doc("ToDo", name, true);
		}
	});

	async function link_dialog(desk, df = {}) {
		return desk.dialog({
			title: "Picker",
			fields: [
				{
					label: "Select ToDo",
					fieldname: "link",
					fieldtype: "Link",
					options: "ToDo",
					...df,
				},
			],
		});
	}

	const picker = (page) => page.locator(".link-picker-dialog");
	const rows = (page) => picker(page).locator("tbody tr");

	test("the button is visible, named, and the dropdown still works", async ({ page, desk }) => {
		const dialog = await link_dialog(desk);
		const button = page.locator(".modal.show .btn-link-select");
		await expect(button).toBeVisible();
		await expect(button).toHaveAttribute("aria-label", /Select from list: Select ToDo/);

		const input = page.locator(".frappe-control[data-fieldname=link] input");
		await input.focus();
		await input.pressSequentially(stamp, { delay: 50 });
		const option = input.locator("xpath=..").getByRole("listbox").locator("div[role='option']").first();
		await expect(option).toContainText(stamp);
		await input.press("Enter");
		await expect.poll(() => dialog.evaluate((d) => d.get_value("link"))).toBeTruthy();
	});

	test("double click selects, fires change and closes", async ({ page, desk }) => {
		const dialog = await link_dialog(desk);
		await page.evaluate(() => {
			window.__changes = [];
			cur_dialog.get_field("link").df.change = () => window.__changes.push(1);
		});
		await page.locator(".modal.show .btn-link-select").click();
		await expect(picker(page)).toBeVisible();
		await picker(page).locator("input[data-fieldname=txt]").fill(stamp);
		await expect(rows(page)).toHaveCount(3);
		await picker(page).locator("input[data-fieldname=txt]").fill(`beta ${stamp}`);
		await expect(rows(page)).toHaveCount(1);
		await rows(page).first().dblclick();
		await expect(picker(page)).toBeHidden();
		await expect.poll(() => dialog.evaluate((d) => d.get_value("link"))).toBe(todos[1]);
		expect(await page.evaluate(() => window.__changes.length)).toBeGreaterThan(0);
	});

	test("F4, arrows and Enter select from the keyboard", async ({ page, desk }) => {
		const dialog = await link_dialog(desk);
		const input = page.locator(".frappe-control[data-fieldname=link] input");
		await input.focus();
		await input.press("F4");
		await expect(picker(page)).toBeVisible();
		const search = picker(page).locator("input[data-fieldname=txt]");
		await expect(search).toBeFocused();
		await search.fill(stamp);
		await expect(rows(page)).toHaveCount(3);
		await search.press("ArrowDown");
		const active = picker(page).locator("tr.is-active");
		await expect(active).toHaveAttribute("aria-selected", "true");
		const expected = await active.getAttribute("id");
		await expect(search).toHaveAttribute("aria-activedescendant", expected);
		const name = await active.evaluate((tr) => tr.cells[0].textContent.trim());
		await search.press("Enter");
		await expect(picker(page)).toBeHidden();
		await expect.poll(() => dialog.evaluate((d) => d.get_value("link"))).toBe(name);
		await expect(input).toBeFocused();
	});

	test("Esc closes without changing the value", async ({ page, desk }) => {
		const dialog = await link_dialog(desk);
		await dialog.evaluate((d, v) => d.set_value("link", v), todos[0]);
		await expect.poll(() => dialog.evaluate((d) => d.get_value("link"))).toBe(todos[0]);
		await page.locator(".modal.show .btn-link-select").click();
		await expect(picker(page)).toBeVisible();
		// Bootstrap ignores a hide while the dialog is still fading in
		await page.waitForFunction(() => cur_dialog?.display && cur_dialog.title.startsWith("Select"));
		await picker(page).locator("input[data-fieldname=txt]").press("Escape");
		await expect(picker(page)).toBeHidden();
		expect(await dialog.evaluate((d) => d.get_value("link"))).toBe(todos[0]);
	});

	test("get_query filters apply and are described", async ({ page, desk }) => {
		await link_dialog(desk);
		await page.evaluate((stamp) => {
			cur_dialog.get_field("link").get_query = () => ({
				filters: { description: ["like", `%alpha ${stamp}%`] },
			});
		}, stamp);
		await page.locator(".modal.show .btn-link-select").click();
		await expect(picker(page)).toBeVisible();
		await expect(rows(page)).toHaveCount(1);
		await expect(picker(page).locator(".link-picker-filters")).toContainText("Filtered by");
	});

	test("no button on a read-only field", async ({ page, desk }) => {
		await link_dialog(desk, { read_only: 1 });
		await expect(page.locator(".frappe-control[data-fieldname=link]")).toBeVisible();
		await expect(page.locator(".btn-link-select:visible")).toHaveCount(0);
	});

	test("a Dynamic Link without a type shows a hint, not the list", async ({ page, desk }) => {
		await desk.dialog({
			title: "Dyn",
			fields: [
				{ label: "Type", fieldname: "kind", fieldtype: "Link", options: "DocType" },
				{ label: "Doc", fieldname: "doc", fieldtype: "Dynamic Link", options: "kind" },
			],
		});
		const input = page.locator(".frappe-control[data-fieldname=doc] input");
		await input.focus();
		await input.press("F4");
		await expect(page.locator(".es-toast").first()).toContainText("First select the type");
		await expect(picker(page)).toHaveCount(0);
	});
});

test.describe("Link field in a table cell: select from list", () => {
	let todo;
	const table = (page) => page.locator('.frappe-control[data-fieldname="links"]');
	const cell_input = (page, fieldname) =>
		table(page).locator(`.grid-body .grid-row[data-idx="1"] input[data-fieldname="${fieldname}"]`);

	test.beforeEach(async ({ desk, page, api }) => {
		[todo] = await api.create_records([
			{ doctype: "ToDo", description: `grid picker ${Date.now()}` },
		]);
		await desk.new_form("Contact");
		await table(page).locator(".grid-add-row").click();
		await page.evaluate(() => {
			const row = cur_frm.doc.links[0];
			frappe.model.set_value(row.doctype, row.name, "link_doctype", "ToDo");
		});
	});

	test.afterEach(async ({ admin }) => {
		await admin.remove_doc("ToDo", todo, true);
	});

	test("the button is in the editable cell; F4 picks a value and the row stays editable", async ({
		page,
	}) => {
		const input = cell_input(page, "link_name");
		await input.focus();
		const button = table(page).locator('.grid-body .grid-row[data-idx="1"] .btn-link-select:visible');
		await expect(button).toHaveCount(2); // link_doctype and link_name
		await expect(button.last()).toHaveAttribute("tabindex", "-1");
		await input.press("F4");
		const dialog = page.locator(".link-picker-dialog");
		await expect(dialog).toBeVisible();
		await page.waitForFunction(() => cur_dialog?.display && cur_dialog.title.startsWith("Select"));
		const search = dialog.locator("input[data-fieldname=txt]");
		await search.fill(todo);
		await expect(dialog.locator("tbody tr")).toHaveCount(1);
		await dialog.locator("tbody tr").first().dblclick();
		await expect(dialog).toBeHidden();
		await expect
			.poll(() => page.evaluate(() => cur_frm.doc.links[0].link_name))
			.toBe(todo);
		await expect(input).toBeVisible();
		await expect(input).toBeFocused();
	});
});
