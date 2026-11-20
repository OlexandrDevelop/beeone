// "Date and time" as ONE input with a mask (user 2026-11-20): "dd-mm-yyyy HH:mm:ss" in the system date order.
// The date and the time stay two real fields of the document (beeone.form.PAIRS); this input only shows and edits them.
// Editing like 1C: digits overwrite the mask under the cursor and the cursor skips the separators, Backspace/Delete
// clear a digit, ↑/↓ change the part under the cursor (day, month, year, hour, minute, second), the calendar button
// opens the browser's date-time picker. The value is written on Enter or when the input loses the focus; an incomplete
// year takes the current one, an empty time takes 00:00:00, an impossible date restores the document's value.
frappe.provide("beeone.form");

(function () {
	const F = beeone.form;
	const BLANK = "_";
	const LIMITS = {
		day: [1, 31],
		month: [1, 12],
		year: [1900, 2999],
		hour: [0, 23],
		minute: [0, 59],
		second: [0, 59],
	};

	// the mask in the system date order: [{type, start, len}], text with "_" in every digit place
	F.dt_layout = function () {
		const date_format = ((frappe.boot && frappe.boot.sysdefaults && frappe.boot.sysdefaults.date_format) || "dd-mm-yyyy").toLowerCase();
		const segs = [];
		let text = "";
		date_format.replace(/(d+|m+|y+|[^dmy]+)/g, (token) => {
			const type = { d: "day", m: "month", y: "year" }[token[0]];
			if (type) {
				const len = type === "year" ? 4 : 2;
				segs.push({ type, start: text.length, len });
				text += BLANK.repeat(len);
			} else text += token;
			return token;
		});
		text += " ";
		["hour", "minute", "second"].forEach((type, i) => {
			if (i) text += ":";
			segs.push({ type, start: text.length, len: 2 });
			text += BLANK.repeat(2);
		});
		return { segs, empty: text };
	};

	const pad = (v, len) => String(v).padStart(len, "0");
	const is_slot = (layout, pos) => layout.segs.some((s) => pos >= s.start && pos < s.start + s.len);
	const seg_at = (layout, pos) =>
		layout.segs.find((s) => pos >= s.start && pos <= s.start + s.len) || layout.segs[layout.segs.length - 1];

	// document values ("2026-08-26", "13:00:00") -> masked text
	F.dt_text = function (layout, date, time) {
		const parts = {};
		if (date) {
			const [y, m, d] = String(date).split("-");
			Object.assign(parts, { year: y, month: m, day: d });
		}
		if (time) {
			const [h, mi, s] = String(time).split(".")[0].split(":");
			Object.assign(parts, { hour: h, minute: mi, second: s || "00" });
		}
		let text = layout.empty;
		layout.segs.forEach((seg) => {
			const v = parts[seg.type];
			if (v == null || v === "") return;
			text = text.slice(0, seg.start) + pad(v, seg.len).slice(-seg.len) + text.slice(seg.start + seg.len);
		});
		return text;
	};

	// masked text -> {date, time} | {empty: true} | null (impossible)
	F.dt_parse = function (layout, text) {
		const raw = {};
		layout.segs.forEach((seg) => (raw[seg.type] = text.substr(seg.start, seg.len)));
		const blank = (v) => v.split("").every((c) => c === BLANK);
		if (layout.segs.every((seg) => blank(raw[seg.type]))) return { empty: true };
		const now = new Date();
		const num = (type, fallback) => {
			const v = raw[type];
			if (blank(v)) return fallback;
			if (v.includes(BLANK)) {
				// a part typed in short: "5_" is 5, a two-digit year "26__" is 2026
				const digits = v.replace(new RegExp(BLANK, "g"), "");
				if (type === "year") return digits.length <= 2 ? 2000 + cint(digits) : null;
				return cint(digits);
			}
			return cint(v);
		};
		const p = {
			day: num("day", null),
			month: num("month", now.getMonth() + 1),
			year: num("year", now.getFullYear()),
			hour: num("hour", 0),
			minute: num("minute", 0),
			second: num("second", 0),
		};
		if (Object.values(p).some((v) => v == null)) return null;
		for (const [type, [lo, hi]] of Object.entries(LIMITS)) if (p[type] < lo || p[type] > hi) return null;
		const check = new Date(p.year, p.month - 1, p.day);
		if (check.getMonth() !== p.month - 1) return null; // 31.02
		return {
			date: `${pad(p.year, 4)}-${pad(p.month, 2)}-${pad(p.day, 2)}`,
			time: `${pad(p.hour, 2)}:${pad(p.minute, 2)}:${pad(p.second, 2)}`,
		};
	};

	// the input of a pair cell; a, b = the date and the time controls of the form
	F.dt_input = function (frm, a, b, $cell) {
		const layout = F.dt_layout();
		const $box = $(
			`<div class="bf-dt-box">` +
				`<input type="text" class="form-control bf-dt-input" inputmode="numeric" autocomplete="off" spellcheck="false">` +
				`<button type="button" class="bf-dt-cal" tabindex="-1" title="${frappe.utils.escape_html(__("Calendar"))}">` +
				`${frappe.utils.icon("calendar", "sm")}</button>` +
				`<input type="datetime-local" step="1" class="bf-dt-native" tabindex="-1" aria-hidden="true">` +
				`</div>`
		);
		const input = $box.find(".bf-dt-input")[0];
		const native = $box.find(".bf-dt-native")[0];
		input.setAttribute("aria-label", __("Date and time"));
		input.placeholder = layout.empty;

		const editable = () => !input.readOnly;
		const set_text = (text, caret) => {
			input.value = text;
			if (caret != null) input.setSelectionRange(caret, caret);
		};
		const next_slot = (pos, dir) => {
			while (pos >= 0 && pos < layout.empty.length && !is_slot(layout, pos)) pos += dir;
			return pos;
		};
		const clear_range = (text, from, to) => {
			let out = text;
			for (let i = from; i < to; i++) if (is_slot(layout, i)) out = out.slice(0, i) + BLANK + out.slice(i + 1);
			return out;
		};

		const render = () => {
			if (document.activeElement === input) return; // never under the user's cursor
			set_text(F.dt_text(layout, frm.doc[a.df.fieldname], frm.doc[b.df.fieldname]));
			const state = a.$wrapper.attr("data-bo-state") || "edit";
			const writable = a.get_status() === "Write" || b.get_status() === "Write";
			input.readOnly = !writable;
			$cell.attr("data-bo-state", writable ? "edit" : state === "edit" ? "text" : state);
			$cell.attr("data-bo-reqd", a.df.reqd || b.df.reqd ? "1" : "0");
			$cell.attr("data-bo-empty", frm.doc[a.df.fieldname] ? "0" : "1");
			$cell.toggleClass("has-error", a.$wrapper.hasClass("has-error") || b.$wrapper.hasClass("has-error"));
			$box.find(".bf-dt-cal").prop("hidden", !writable);
		};

		const commit = () => {
			if (!editable()) return;
			const parsed = F.dt_parse(layout, input.value);
			const cur_date = frm.doc[a.df.fieldname] || "";
			const cur_time = frm.doc[b.df.fieldname] || "";
			if (!parsed) {
				frappe.show_alert({ message: __("Invalid date or time"), indicator: "red" }, 3);
				set_text(F.dt_text(layout, cur_date, cur_time));
				return;
			}
			const date = parsed.empty ? "" : parsed.date;
			const time = parsed.empty ? "" : parsed.time;
			const jobs = [];
			if (date !== cur_date) jobs.push(frm.set_value(a.df.fieldname, date));
			if (time !== String(cur_time).split(".")[0]) jobs.push(frm.set_value(b.df.fieldname, time));
			Promise.all(jobs).then(() => set_text(F.dt_text(layout, frm.doc[a.df.fieldname], frm.doc[b.df.fieldname])));
		};

		const step = (dir) => {
			const pos = input.selectionStart;
			const seg = seg_at(layout, pos);
			let text = input.value || layout.empty;
			const v = text.substr(seg.start, seg.len);
			const now = new Date();
			const current = {
				day: now.getDate(),
				month: now.getMonth() + 1,
				year: now.getFullYear(),
				hour: now.getHours(),
				minute: now.getMinutes(),
				second: now.getSeconds(),
			}[seg.type];
			const [lo, hi] = LIMITS[seg.type];
			let n = v.includes(BLANK) ? current : cint(v) + dir;
			if (n > hi) n = lo;
			if (n < lo) n = hi;
			text = text.slice(0, seg.start) + pad(n, seg.len) + text.slice(seg.start + seg.len);
			set_text(text);
			input.setSelectionRange(seg.start, seg.start + seg.len);
		};

		input.addEventListener("focus", () => {
			if (!input.value) set_text(layout.empty, 0);
		});
		input.addEventListener("keydown", (e) => {
			if (!editable() || e.ctrlKey || e.metaKey || e.altKey) return;
			const text = input.value || layout.empty;
			const from = input.selectionStart;
			const to = input.selectionEnd;
			if (/^\d$/.test(e.key)) {
				e.preventDefault();
				let base = from !== to ? clear_range(text, from, to) : text;
				const pos = next_slot(from, 1);
				if (pos < 0 || pos >= layout.empty.length) return;
				base = base.slice(0, pos) + e.key + base.slice(pos + 1);
				set_text(base, next_slot(pos + 1, 1) >= layout.empty.length ? pos + 1 : next_slot(pos + 1, 1));
			} else if (e.key === "Backspace") {
				e.preventDefault();
				if (from !== to) return set_text(clear_range(text, from, to), from);
				const pos = next_slot(from - 1, -1);
				if (pos < 0) return;
				set_text(clear_range(text, pos, pos + 1), pos);
			} else if (e.key === "Delete") {
				e.preventDefault();
				if (from !== to) return set_text(clear_range(text, from, to), from);
				const pos = next_slot(from, 1);
				if (pos >= layout.empty.length) return;
				set_text(clear_range(text, pos, pos + 1), pos);
			} else if (e.key === "ArrowUp" || e.key === "ArrowDown") {
				e.preventDefault();
				e.stopPropagation(); // not the list/grid navigation of the shell
				step(e.key === "ArrowUp" ? 1 : -1);
			} else if (e.key === "Enter") {
				commit();
			} else if (e.key === "Escape") {
				set_text(F.dt_text(layout, frm.doc[a.df.fieldname], frm.doc[b.df.fieldname]));
			} else if (e.key.length === 1) {
				// separators and letters are not typed: the mask has them; a separator jumps to the next part
				e.preventDefault();
				if (/[\s.\-/:]/.test(e.key)) {
					const seg = seg_at(layout, from);
					const i = layout.segs.indexOf(seg);
					const next = layout.segs[i + 1];
					if (next) input.setSelectionRange(next.start, next.start);
				}
			}
		});
		input.addEventListener("paste", (e) => {
			if (!editable()) return;
			e.preventDefault();
			const digits = ((e.clipboardData || window.clipboardData).getData("text") || "").replace(/\D/g, "");
			let text = layout.empty;
			let pos = 0;
			for (const d of digits) {
				pos = next_slot(pos, 1);
				if (pos >= layout.empty.length) break;
				text = text.slice(0, pos) + d + text.slice(pos + 1);
				pos += 1;
			}
			set_text(text, pos);
		});
		input.addEventListener("blur", commit);

		$box.find(".bf-dt-cal").on("click", () => {
			if (!editable()) return;
			const date = frm.doc[a.df.fieldname] || frappe.datetime.get_today();
			const time = String(frm.doc[b.df.fieldname] || "00:00:00").split(".")[0];
			native.value = `${date}T${time}`;
			try {
				native.showPicker();
			} catch (err) {
				native.focus();
			}
		});
		native.addEventListener("change", () => {
			if (!native.value) return;
			const [date, time] = native.value.split("T");
			set_text(F.dt_text(layout, date, (time || "00:00:00").length === 5 ? time + ":00" : time));
			commit();
		});

		// the controls refresh on every form refresh and value change: the input follows them
		[a, b].forEach((control) => {
			const refresh = control.refresh.bind(control);
			control.refresh = function () {
				const out = refresh(...arguments);
				render();
				return out;
			};
			const set_formatted = control.set_formatted_input && control.set_formatted_input.bind(control);
			if (set_formatted) {
				control.set_formatted_input = function () {
					const out = set_formatted(...arguments);
					render();
					return out;
				};
			}
		});
		render();
		return $box;
	};
})();
