import { test, expect } from "../support";

// T-864: Enter / Esc navigation in editable grid cells and the closed-by-default form sidebar.
const table = (page) => page.locator('.frappe-control[data-fieldname="email_ids"]');

test.describe("Grid inline keyboard", () => {
	test.beforeEach(async ({ page, desk }) => {
		await desk.new_form("Contact");
		await table(page).locator(".grid-add-row").click();
	});

	test("Enter in the last cell adds a row and moves into it", async ({ page }) => {
		const first = table(page).locator('.grid-body .grid-row [data-fieldname="email_id"] input').first();
		await first.fill("a@example.com");
		await page.keyboard.press("Enter");
		await expect(table(page).locator(".grid-body .grid-row")).toHaveCount(2);
		await expect(
			table(page).locator('.grid-body .grid-row[data-idx="2"] input[data-fieldname="email_id"]')
		).toBeFocused();
	});

	test("Esc puts the cell value back, the second Esc leaves row editing", async ({ page }) => {
		const input = table(page).locator('.grid-body .grid-row [data-fieldname="email_id"] input').first();
		await input.fill("keep@example.com");
		await page.keyboard.press("Enter");
		const second = table(page)
			.locator('.grid-body .grid-row[data-idx="2"] input[data-fieldname="email_id"]')
			.first();
		await second.fill("x@example.com");
		await page.keyboard.press("Tab");
		await table(page).locator('.grid-body .grid-row[data-idx="1"] [data-fieldname="email_id"]').click();
		const cell = table(page).locator('.grid-body .grid-row[data-idx="1"] input[data-fieldname="email_id"]');
		await cell.fill("changed@example.com");
		await page.keyboard.press("Escape");
		await expect(cell).toHaveValue("keep@example.com");
		await page.keyboard.press("Escape");
		await expect(table(page).locator('.grid-body .grid-row[data-idx="1"] .editable-row')).toHaveCount(0);
	});

	test("the form sidebar is closed until it is opened", async ({ page }) => {
		await expect(page.locator(".layout-side-section")).toBeHidden();
	});
});
