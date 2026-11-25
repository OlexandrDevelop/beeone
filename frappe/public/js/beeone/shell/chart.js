// Desktop widget "Chart for the period" (beeone.chart): a time series of a sum, split into series (one per organization,
// department…). Plain SVG, no library: 2px lines, a soft area, stacked bars with a 2px gap, a crosshair with one
// tooltip for every series, a legend with the totals that hides a series on click (the colour stays with the series),
// a table view in the expanded window. Colours: --bo-series-1…6 (validated light/dark), «Others» is neutral.

const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
const SVG = "http://www.w3.org/2000/svg";
const MONTHS = () => [...Array(12)].map((_, m) => new Intl.DateTimeFormat("uk", { month: "short" }).format(new Date(2026, m, 1)).replace(".", ""));
const MONTHS_LONG = () => [...Array(12)].map((_, m) => new Intl.DateTimeFormat("uk", { month: "long" }).format(new Date(2026, m, 1)));

export function series_color(s, i) {
	return s.other ? "var(--bo-series-other)" : `var(--bo-series-${(i % 6) + 1})`;
}

// 1 234 567 -> "1.2 mln", 350 000 -> "350 thousand" (translated)
export function compact(value) {
	const a = Math.abs(value);
	const short = (v) => format_number(v, null, Number.isInteger(Math.round(v * 10) / 10) || Math.abs(v) >= 10 ? 0 : 1);
	if (a >= 1e9) return `${short(value / 1e9)} ${__("bn")}`;
	if (a >= 1e6) return `${short(value / 1e6)} ${__("mln")}`;
	if (a >= 1e3) return `${format_number(value / 1e3, null, 0)} ${__("thousand")}`;
	return format_number(value, null, 0);
}

function money(value, currency) {
	return beeone.ui.money(value, { digits: Math.abs(value) >= 1000 ? 0 : 2, cur: currency });
}

function nice_max(v) {
	if (v <= 0) return 1;
	const p = Math.pow(10, Math.floor(Math.log10(v)));
	const n = v / p;
	// a scale that leaves little empty space: the first «round» step at or above the maximum
	const step = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((k) => n <= k + 1e-9);
	return step * p;
}

// the change against the previous period of the same length (only for the visible series)
function delta_html(d, visible) {
	const prev = visible.reduce((a, s) => a + (s.previous || 0), 0);
	const now = visible.reduce((a, s) => a + s.total, 0);
	if (!prev) return "";
	const change = ((now - prev) / Math.abs(prev)) * 100;
	const up = change >= 0;
	return `<span class="bo-w-delta ${up ? "is-up" : "is-down"}" title="${esc(__("Against the previous period: {0}", [money(prev, d.currency)]))}">${up ? "▲" : "▼"} ${esc(format_number(Math.abs(change), null, 1))}%</span>`;
}

export function bucket_label(d, i, long) {
	const date = frappe.datetime.str_to_obj(d.buckets[i]);
	if (d.bucket === "month") {
		const m = date.getMonth();
		if (long) return `${MONTHS_LONG()[m]} ${date.getFullYear()}`;
		return m === 0 || i === 0 ? `${MONTHS()[m]} ’${String(date.getFullYear()).slice(2)}` : MONTHS()[m];
	}
	const dd = frappe.datetime.str_to_user(d.buckets[i]).slice(0, 5);
	if (d.bucket === "week") return long ? __("Week from {0}", [frappe.datetime.str_to_user(d.buckets[i])]) : dd;
	return long ? frappe.datetime.str_to_user(d.buckets[i]) : dd;
}

const PERIOD_LABEL = () => ({ "12m": __("Last 12 months"), ytd: __("This year"), "90d": __("Last 90 days"), "30d": __("Last 30 days") });

function el(tag, attrs, parent) {
	const node = document.createElementNS(SVG, tag);
	for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
	if (parent) parent.appendChild(node);
	return node;
}

// The chart into `host` (a sized element). `state.hidden` keeps the hidden series between redraws.
export function render_chart(host, d, opts) {
	opts = opts || {};
	const style = ["line", "area", "bar"].includes(opts.style) ? opts.style : "area";
	const state = host.__bo_chart || (host.__bo_chart = { hidden: new Set() });
	const series = d.series.map((s, i) => ({ ...s, color: series_color(s, i) }));
	const visible = series.filter((s) => !state.hidden.has(s.key));
	const n = d.buckets.length;
	const visible_total = visible.reduce((a, s) => a + s.total, 0);

	host.classList.add("bo-chart");
	host.innerHTML =
		`<div class="bo-chart-head"><div class="bo-chart-total">${esc(money(visible_total, d.currency))}</div>` +
		(delta_html(d, visible)) +
		`<div class="bo-chart-period">${esc(PERIOD_LABEL()[d.period] || "")}${d.group_label ? " · " + esc(__("by {0}", [d.group_label.toLowerCase()])) : ""}</div></div>` +
		(series.length > 1
			? `<div class="bo-chart-legend" role="list">${series
					.map(
						(s) =>
							`<button type="button" role="listitem" class="bo-chart-key${state.hidden.has(s.key) ? " is-off" : ""}" data-key="${esc(s.key)}" aria-pressed="${!state.hidden.has(s.key)}" title="${esc(__("Show or hide"))}">` +
							`<i class="${style === "line" ? "is-line" : ""}" style="--c:${s.color}"></i><span class="bo-chart-key-label">${esc(s.label)}</span><b>${esc(compact(s.total))}</b></button>`
					)
					.join("")}</div>`
			: "") +
		`<div class="bo-chart-plot"></div><div class="bo-chart-tip" hidden></div>`;

	host.querySelectorAll(".bo-chart-key").forEach((b) =>
		b.addEventListener("click", (e) => {
			e.stopPropagation();
			const key = b.dataset.key;
			if (state.hidden.has(key)) state.hidden.delete(key);
			else if (visible.length > 1) state.hidden.add(key); // at least one series stays
			render_chart(host, d, opts);
		})
	);

	const plot = host.querySelector(".bo-chart-plot");
	const W = Math.max(plot.clientWidth, 200);
	const H = Math.max(plot.clientHeight, 90);
	const big = W > 520;
	const pad = { l: 46, r: big && style !== "bar" && visible.length <= 4 && visible.length > 1 ? 104 : 10, t: 8, b: 22 };
	const iw = W - pad.l - pad.r;
	const ih = H - pad.t - pad.b;

	if (!visible_total && !visible.some((s) => s.values.some((v) => v))) {
		plot.innerHTML = `<div class="bo-chart-empty">${esc(__("No data for the period"))}</div>`;
		return;
	}

	const stacked = style === "bar";
	const sums = [...Array(n)].map((_, i) => visible.reduce((a, s) => a + (s.values[i] || 0), 0));
	const raw_max = stacked ? Math.max(...sums) : Math.max(...visible.flatMap((s) => s.values));
	const raw_min = stacked ? 0 : Math.min(0, ...visible.flatMap((s) => s.values));
	const max = nice_max(raw_max);
	const min = raw_min < 0 ? -nice_max(-raw_min) : 0;
	const y = (v) => pad.t + ih - ((v - min) / (max - min || 1)) * ih;
	const step = stacked ? iw / n : iw / Math.max(n - 1, 1);
	const x = (i) => (stacked ? pad.l + step * i + step / 2 : pad.l + step * i);

	const svg = el("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": `${d.label}: ${money(visible_total, d.currency)}` }, plot);
	const defs = el("defs", {}, svg);

	// recessive grid: 4 lines, compact labels
	const grid = el("g", { class: "bo-chart-grid" }, svg);
	for (let k = 0; k <= 4; k++) {
		const v = min + ((max - min) * k) / 4;
		const yy = Math.round(y(v)) + 0.5;
		el("line", { x1: pad.l, x2: W - pad.r, y1: yy, y2: yy, class: v === 0 ? "is-zero" : "" }, grid);
		const t = el("text", { x: pad.l - 8, y: yy + 3.5, "text-anchor": "end" }, grid);
		t.textContent = compact(v);
	}
	// x labels: as many as fit
	const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(iw / (big ? 64 : 46)))));
	for (let i = 0; i < n; i++) {
		if ((n - 1 - i) % every) continue; // the current bucket always has its label
		const t = el("text", { x: x(i), y: H - 6, "text-anchor": i === 0 && !stacked ? "start" : i === n - 1 && !stacked ? "end" : "middle" }, grid);
		t.textContent = bucket_label(d, i);
	}

	const marks = el("g", {}, svg);
	if (stacked) {
		const bw = Math.max(3, Math.min(36, step * 0.62));
		for (let i = 0; i < n; i++) {
			let acc = 0;
			const parts = visible.filter((s) => s.values[i] > 0);
			parts.forEach((s, j) => {
				const v = s.values[i];
				const y0 = y(acc), y1 = y(acc + v);
				acc += v;
				const top = j === parts.length - 1;
				const gap = j ? 2 : 0; // a 2px surface gap between the segments
				const h = Math.max(0, y0 - y1 - gap);
				const x0 = x(i) - bw / 2;
				const r = top ? Math.min(4, bw / 2, h) : 0;
				const p = `M${x0},${y1 + h}V${y1 + r}${r ? `Q${x0},${y1} ${x0 + r},${y1}` : ""}H${x0 + bw - r}${r ? `Q${x0 + bw},${y1} ${x0 + bw},${y1 + r}` : ""}V${y1 + h}Z`;
				el("path", { d: p, fill: s.color, class: "bo-chart-bar", "data-i": i }, marks);
			});
		}
	} else {
		visible.forEach((s, j) => {
			const pts = s.values.map((v, i) => [x(i), y(v)]);
			const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("");
			if (style === "area") {
				const id = `bo-g-${Math.random().toString(36).slice(2)}`;
				const g = el("linearGradient", { id, x1: 0, x2: 0, y1: 0, y2: 1 }, defs);
				el("stop", { offset: "0%", "stop-color": s.color, "stop-opacity": visible.length > 1 ? 0.16 : 0.24 }, g);
				el("stop", { offset: "100%", "stop-color": s.color, "stop-opacity": 0 }, g);
				el("path", { d: `${line}L${x(n - 1)},${y(Math.max(min, 0))}L${x(0)},${y(Math.max(min, 0))}Z`, fill: `url(#${id})` }, marks);
			}
			el("path", { d: line, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round", class: "bo-chart-line" }, marks);
			// the current bucket: a marker with a surface ring
			const last = pts[n - 1];
			el("circle", { cx: last[0], cy: last[1], r: 4, fill: s.color, class: "bo-chart-dot" }, marks);
			if (pad.r > 20) {
				const t = el("text", { x: last[0] + 10, y: last[1] + 4, class: "bo-chart-direct" }, svg);
				t.textContent = s.label.length > 14 ? s.label.slice(0, 13) + "…" : s.label;
			}
		});
		// direct labels must not collide: push them apart vertically
		const labels = [...svg.querySelectorAll(".bo-chart-direct")].sort((a, b) => +a.getAttribute("y") - +b.getAttribute("y"));
		for (let k = 1; k < labels.length; k++) {
			const prev = +labels[k - 1].getAttribute("y");
			if (+labels[k].getAttribute("y") - prev < 14) labels[k].setAttribute("y", prev + 14);
		}
	}

	// hover: a crosshair (lines) or the column (bars), one tooltip with every series; the keyboard moves it too
	const cross = el("line", { y1: pad.t, y2: pad.t + ih, class: "bo-chart-cross", visibility: "hidden" }, svg);
	const dots = el("g", { visibility: "hidden" }, svg);
	const hit = el("rect", { x: pad.l - 6, y: 0, width: iw + 12, height: H, fill: "transparent", tabindex: 0, class: "bo-chart-hit" }, svg);
	const tip = host.querySelector(".bo-chart-tip");
	const show = (i) => {
		i = Math.max(0, Math.min(n - 1, i));
		state.at = i;
		cross.setAttribute("x1", x(i));
		cross.setAttribute("x2", x(i));
		cross.setAttribute("visibility", stacked ? "hidden" : "visible");
		dots.innerHTML = "";
		if (!stacked) visible.forEach((s) => el("circle", { cx: x(i), cy: y(s.values[i]), r: 4.5, fill: s.color, class: "bo-chart-dot" }, dots));
		dots.setAttribute("visibility", "visible");
		svg.querySelectorAll(".bo-chart-bar").forEach((b) => b.classList.toggle("is-dim", +b.dataset.i !== i));
		const rows = visible.map((s) => ({ s, v: s.values[i] || 0 })).sort((a, b) => b.v - a.v);
		const sum = rows.reduce((a, r) => a + r.v, 0);
		tip.innerHTML =
			`<div class="bo-chart-tip-head">${esc(bucket_label(d, i, true))}</div>` +
			rows.map((r) => `<div class="bo-chart-tip-row"><i style="--c:${r.s.color}"></i><b>${esc(money(r.v, d.currency))}</b><span>${esc(r.s.label)}</span></div>`).join("") +
			(rows.length > 1 ? `<div class="bo-chart-tip-row is-sum"><i></i><b>${esc(money(sum, d.currency))}</b><span>${esc(__("Total"))}</span></div>` : "");
		tip.hidden = false;
		// beside the crosshair: to the right when it fits, else to the left; never over the plotted column
		const box = plot.getBoundingClientRect(), hb = host.getBoundingClientRect();
		const left = box.left - hb.left + x(i);
		const tw = tip.offsetWidth;
		tip.style.left = `${left + 14 + tw <= hb.width ? left + 14 : Math.max(0, left - 14 - tw)}px`;
		tip.style.top = `${Math.max(0, box.top - hb.top + 4)}px`;
	};
	const hide = () => {
		cross.setAttribute("visibility", "hidden");
		dots.setAttribute("visibility", "hidden");
		svg.querySelectorAll(".bo-chart-bar").forEach((b) => b.classList.remove("is-dim"));
		tip.hidden = true;
	};
	hit.addEventListener("pointermove", (e) => {
		const r = svg.getBoundingClientRect();
		const px = e.clientX - r.left;
		show(stacked ? Math.floor((px - pad.l) / step) : Math.round((px - pad.l) / step));
	});
	hit.addEventListener("pointerleave", hide);
	hit.addEventListener("focus", () => show(state.at ?? n - 1));
	hit.addEventListener("blur", hide);
	hit.addEventListener("keydown", (e) => {
		if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
			e.preventDefault();
			show((state.at ?? n - 1) + (e.key === "ArrowLeft" ? -1 : 1));
		}
	});
}

// The table view of the expanded window (every value without hovering)
export function chart_table(d) {
	const head = `<tr><th>${esc(__("Period"))}</th>${d.series.map((s) => `<th class="num">${esc(s.label)}</th>`).join("")}${d.series.length > 1 ? `<th class="num">${esc(__("Total"))}</th>` : ""}</tr>`;
	const rows = d.buckets
		.map((_, i) => {
			const sum = d.series.reduce((a, s) => a + (s.values[i] || 0), 0);
			return `<tr><td>${esc(bucket_label(d, i, true))}</td>${d.series.map((s) => `<td class="num">${esc(money(s.values[i] || 0, d.currency))}</td>`).join("")}${d.series.length > 1 ? `<td class="num"><b>${esc(money(sum, d.currency))}</b></td>` : ""}</tr>`;
		})
		.reverse()
		.join("");
	const foot = `<tr><td><b>${esc(__("Total"))}</b></td>${d.series.map((s) => `<td class="num"><b>${esc(money(s.total, d.currency))}</b></td>`).join("")}${d.series.length > 1 ? `<td class="num"><b>${esc(money(d.total, d.currency))}</b></td>` : ""}</tr>`;
	return `<table class="bo-chart-table"><thead>${head}</thead><tbody>${rows}</tbody><tfoot>${foot}</tfoot></table>`;
}
