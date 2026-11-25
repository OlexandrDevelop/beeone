// The AI assistant panel (frappe.beeone.ai): a side panel that answers questions about using the program and
// about the data, runs the checks of the apps with a button, opens the documents it links and the ones it proposes.
// Without a model it still shows the help pages that fit the question and the checks.
const { icon, esc } = beeone.ui;
const API = "frappe.beeone.ai.api.";
const STORE = "beeone_ai_chat";
const MAX_KEPT = 30;

let boot = null;
let chat = [];
let busy = false;

function el() {
	return document.getElementById("bo-ai");
}

function save() {
	try {
		sessionStorage.setItem(STORE, JSON.stringify(chat.slice(-MAX_KEPT)));
	} catch (e) {
		// storage is off: the chat lasts until the reload
	}
}

function load() {
	try {
		chat = JSON.parse(sessionStorage.getItem(STORE) || "[]");
	} catch (e) {
		chat = [];
	}
}

function current_route() {
	try {
		return (frappe.get_route() || []).map(String).slice(0, 3);
	} catch (e) {
		return [];
	}
}

// markdown of the model: the HTML is escaped first, links go only to the desk or to https pages
function render_md(text) {
	const html = frappe.markdown(esc(text || ""));
	const box = document.createElement("div");
	box.innerHTML = html;
	box.querySelectorAll("a").forEach((a) => {
		const href = a.getAttribute("href") || "";
		if (/^\/(desk|app)\//.test(href)) {
			a.dataset.desk = href;
			a.setAttribute("href", href);
		} else if (/^https:\/\//.test(href)) {
			a.target = "_blank";
			a.rel = "noopener noreferrer";
		} else {
			a.replaceWith(document.createTextNode(a.textContent));
		}
	});
	box.querySelectorAll("script, iframe, object, embed, img").forEach((n) => n.remove());
	return box.innerHTML;
}

function open_desk(href) {
	const path = decodeURIComponent(href.replace(/^\/(desk|app)\//, ""));
	frappe.set_route(path);
}

function build() {
	if (el()) return el();
	const aside = document.createElement("aside");
	aside.id = "bo-ai";
	aside.className = "bo-ai";
	aside.setAttribute("aria-label", __("AI assistant"));
	aside.hidden = true;
	aside.innerHTML =
		`<header class="bo-ai-head"><span class="bo-ai-mark">${icon("sparkle")}</span><h2>${esc(__("AI assistant"))}</h2>` +
		`<span class="bo-ai-left" data-left></span>` +
		`<button type="button" class="bo-ai-btn" data-ai="new" title="${esc(__("New chat"))}" aria-label="${esc(__("New chat"))}">${icon("plus")}</button>` +
		`<button type="button" class="bo-ai-btn" data-ai="close" title="${esc(__("Close"))} (Alt A)" aria-label="${esc(__("Close"))}">${icon("x")}</button></header>` +
		`<div class="bo-ai-log" data-log role="log" aria-live="polite"></div>` +
		`<form class="bo-ai-form" data-form><textarea rows="2" data-q placeholder="${esc(__("Ask about the program or your data…"))}" aria-label="${esc(__("Question"))}"></textarea>` +
		`<button type="submit" class="bo-btn bo-btn--primary bo-ai-send" aria-label="${esc(__("Send"))}">${icon("arrow-up")}</button></form>`;
	(document.getElementById("bo-app") || document.body).appendChild(aside);
	aside.addEventListener("click", on_click);
	aside.querySelector("[data-form]").addEventListener("submit", (e) => {
		e.preventDefault();
		send();
	});
	aside.querySelector("[data-q]").addEventListener("keydown", (e) => {
		if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
			e.preventDefault();
			send();
		} else if (e.key === "Escape") {
			e.preventDefault();
			close();
		}
	});
	return aside;
}

function on_click(e) {
	const link = e.target.closest("a[data-desk]");
	if (link) {
		e.preventDefault();
		return open_desk(link.dataset.desk);
	}
	const btn = e.target.closest("[data-ai]");
	if (!btn) return;
	const what = btn.dataset.ai;
	if (what === "close") close();
	else if (what === "new") {
		chat = [];
		save();
		paint();
		focus_input();
	} else if (what === "example") ask(btn.dataset.text);
	else if (what === "check") run_check(btn.dataset.tool, btn.dataset.label);
	else if (what === "page") show_page(btn.dataset.page);
	else if (what === "action") run_action(chat[+btn.dataset.m].actions[+btn.dataset.i]);
	else if (what === "rate") rate(+btn.dataset.m, btn.dataset.rating);
	else if (what === "settings") frappe.set_route("Form", "AI Assistant Settings");
}

function focus_input() {
	const q = el() && el().querySelector("[data-q]");
	if (q) q.focus();
}

export function open(question) {
	const aside = build();
	if (aside.hidden) {
		aside.hidden = false;
		aside.classList.add("is-open");
		document.getElementById("bo-app") && document.getElementById("bo-app").classList.add("bo-ai-on");
	}
	if (!boot) {
		load();
		paint();
		frappe
			.xcall(API + "bootstrap")
			.then((b) => {
				boot = b;
				paint();
			})
			.catch(() => {});
	}
	if (question) ask(question);
	else focus_input();
}

export function close() {
	const aside = el();
	if (!aside || aside.hidden) return;
	aside.hidden = true;
	aside.classList.remove("is-open");
	document.getElementById("bo-app") && document.getElementById("bo-app").classList.remove("bo-ai-on");
}

export function toggle() {
	const aside = el();
	if (aside && !aside.hidden) close();
	else open();
}

function left_text() {
	if (!boot) return "";
	if (!boot.ready) return __("Without AI model");
	if (boot.remaining == null || boot.remaining < 0) return "";
	return __("{0} questions left today", [boot.remaining]);
}

function welcome() {
	const b = boot || { checks: [], examples: [] };
	let html = `<div class="bo-ai-welcome"><p>${esc(__("Ask how to do something in the program or what is going on in your data. I read only what you may read and change nothing."))}</p>`;
	if (boot && !boot.ready) {
		html += `<p class="bo-ai-note">${icon("info", "bo-i-sm")}${esc(__("The AI model is not connected: I will show the help pages and run the checks."))}` + (b.is_manager ? ` <button type="button" class="bo-link" data-ai="settings">${esc(__("Connect"))}</button>` : "") + `</p>`;
	}
	if (b.checks.length) {
		html += `<div class="bo-ai-sub">${esc(__("Checks"))}</div><div class="bo-ai-chips">` + b.checks.map((c) => `<button type="button" class="bo-ai-chip" data-ai="check" data-tool="${esc(c.tool)}" data-label="${esc(c.label)}" title="${esc(c.description)}">${icon("checks", "bo-i-sm")}${esc(c.label)}</button>`).join("") + `</div>`;
	}
	if (b.examples.length) {
		html += `<div class="bo-ai-sub">${esc(__("For example"))}</div><div class="bo-ai-chips">` + b.examples.map((x) => `<button type="button" class="bo-ai-chip" data-ai="example" data-text="${esc(x)}">${esc(x)}</button>`).join("") + `</div>`;
	}
	return html + `</div>`;
}

function problems_html(r) {
	const sev = { error: __("Error"), warning: __("Warning"), info: __("Note") };
	let html = `<div class="bo-ai-check"><div class="bo-ai-check-sum ${r.problems.some((p) => p.severity === "error") ? "is-bad" : r.problems.length ? "is-warn" : "is-ok"}">${icon(r.problems.length ? "alert" : "check-circle", "bo-i-sm")}${esc(r.summary || "")}</div>`;
	if (r.problems.length) {
		html += `<ul class="bo-ai-problems">` + r.problems.map((p) => `<li class="is-${esc(p.severity)}"><span class="bo-ai-sev">${esc(sev[p.severity] || p.severity)}</span>` + (p._link ? `<a href="${esc(p._link)}" data-desk="${esc(p._link)}">${esc(p.message)}</a>` : esc(p.message)) + `</li>`).join("") + `</ul>`;
	}
	if (r.checked && r.checked.length) html += `<details class="bo-ai-checked"><summary>${esc(__("What was checked"))}</summary><ul>${r.checked.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></details>`;
	return html + `</div>`;
}

function message_html(m, i) {
	if (m.role === "user") return `<div class="bo-ai-msg is-user"><div class="bo-ai-bubble">${esc(m.text)}</div></div>`;
	if (m.role === "wait") return `<div class="bo-ai-msg is-bot"><div class="bo-ai-bubble bo-ai-wait"><i></i><i></i><i></i><span>${esc(m.text || __("Thinking…"))}</span></div></div>`;
	let html = `<div class="bo-ai-msg is-bot"><div class="bo-ai-bubble">`;
	if (m.check) html += `<div class="bo-ai-title">${esc(m.check.title)}</div>` + problems_html(m.check);
	if (m.text) html += `<div class="bo-ai-md">${render_md(m.text)}</div>`;
	if (m.error) html += `<p class="bo-ai-err">${icon("alert", "bo-i-sm")}${esc(m.error)}</p>`;
	(m.actions || []).forEach((a, k) => {
		html += `<button type="button" class="bo-btn bo-btn--sm bo-btn--primary bo-ai-action" data-ai="action" data-m="${i}" data-i="${k}">${icon("file-plus", "bo-i-sm")}${esc(__("Open new {0}", [a.label]))}</button>` + (a.note ? `<p class="bo-ai-hint">${esc(a.note)}</p>` : "");
	});
	if ((m.checks || []).length) {
		html += `<div class="bo-ai-chips">` + m.checks.map((c) => `<button type="button" class="bo-ai-chip" data-ai="check" data-tool="${esc(c.tool)}" data-label="${esc(c.label)}">${icon("checks", "bo-i-sm")}${esc(c.label)}</button>`).join("") + `</div>`;
	}
	if ((m.sources || []).length) {
		html += `<div class="bo-ai-sources"><span>${esc(__("Help"))}:</span>` + m.sources.map((s) => `<button type="button" class="bo-link" data-ai="page" data-page="${esc(s.page)}">${esc(s.title)}</button>`).join("") + `</div>`;
	}
	if ((m.steps || []).length) {
		html += `<details class="bo-ai-steps"><summary>${esc(__("What I did"))}</summary><ul>${m.steps.map((s) => `<li class="${s.error ? "is-err" : ""}">${esc(s.label)}${s.error ? " — " + esc(s.error) : ""}</li>`).join("")}</ul></details>`;
	}
	if (m.log) {
		html += `<div class="bo-ai-rate">` + ["Helpful", "Not Helpful"].map((r) => `<button type="button" class="bo-ai-btn${m.rating === r ? " is-on" : ""}" data-ai="rate" data-m="${i}" data-rating="${r}" title="${esc(__(r))}" aria-label="${esc(__(r))}" aria-pressed="${m.rating === r}">${icon(r === "Helpful" ? "check" : "x", "bo-i-sm")}</button>`).join("") + `</div>`;
	}
	return html + `</div></div>`;
}

function paint() {
	const aside = el();
	if (!aside) return;
	aside.querySelector("[data-left]").textContent = left_text();
	const log = aside.querySelector("[data-log]");
	log.innerHTML = chat.length ? chat.map(message_html).join("") : welcome();
	log.scrollTop = log.scrollHeight;
	aside.querySelector(".bo-ai-send").disabled = busy;
}

function history() {
	return chat
		.filter((m) => (m.role === "user" || m.role === "bot") && m.text)
		.slice(-6)
		.map((m) => ({ role: m.role === "user" ? "user" : "model", text: m.text }));
}

function send() {
	const q = el().querySelector("[data-q]");
	const text = q.value.trim();
	if (!text || busy) return;
	q.value = "";
	ask(text);
}

function ask(text) {
	if (busy) return;
	const past = history();
	busy = true;
	chat.push({ role: "user", text });
	chat.push({ role: "wait" });
	paint();
	frappe
		.xcall(API + "ask", { question: text, history: JSON.stringify(past), context: JSON.stringify({ route: current_route() }) })
		.then((r) => {
			chat.pop();
			chat.push({ role: "bot", text: r.answer, sources: r.sources, checks: r.status === "Answered" || r.status === "From Cache" ? [] : r.checks, actions: r.actions, steps: r.steps, log: r.log });
			if (boot) boot.remaining = r.remaining;
		})
		.catch((e) => {
			chat.pop();
			chat.push({ role: "bot", error: (e && e.message) || __("Could not get an answer") });
		})
		.finally(() => {
			busy = false;
			save();
			paint();
			focus_input();
		});
}

function run_check(tool, label) {
	if (busy) return;
	busy = true;
	chat.push({ role: "user", text: label });
	chat.push({ role: "wait", text: __("Checking…") });
	paint();
	frappe
		.xcall(API + "run_check", { tool })
		.then((r) => {
			chat.pop();
			chat.push({ role: "bot", check: r });
		})
		.catch((e) => {
			chat.pop();
			chat.push({ role: "bot", error: (e && e.message) || __("The check failed") });
		})
		.finally(() => {
			busy = false;
			save();
			paint();
		});
}

function run_action(a) {
	if (!a || a.type !== "new_doc") return;
	frappe.route_options = Object.assign({}, a.values || {});
	frappe.new_doc(a.doctype);
}

function rate(i, rating) {
	const m = chat[i];
	if (!m || !m.log) return;
	m.rating = rating;
	save();
	paint();
	frappe.xcall(API + "rate", { log: m.log, rating }).catch(() => {});
}

function show_page(page) {
	frappe.xcall(API + "help_page", { page }).then((p) => {
		const box = document.createElement("div");
		box.innerHTML = p.html;
		box.querySelectorAll("script, iframe, object, embed").forEach((n) => n.remove());
		beeone.ui.dialog({
			title: p.title,
			wide: true,
			html: `<div class="bo-dialog-head"><h3>${esc(p.title)}</h3></div><div class="bo-dialog-body bo-ai-page">${box.innerHTML}</div><div class="bo-dialog-foot"><button type="button" class="bo-btn" data-close>${esc(__("Close"))}</button></div>`,
		});
	});
}

frappe.provide("beeone.shell");
beeone.shell.assistant = { open, close, toggle };
