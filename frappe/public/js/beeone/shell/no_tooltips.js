// No tooltips in the application (user 2026-11-23: "remove the tooltips in the whole application, they are superfluous").
// - the native tooltip of a `title` attribute: the text moves to `aria-label` (a screen reader still reads it) and
//   the attribute is dropped, for the page as it is and for every element added or changed later;
// - Bootstrap tooltips (`$(...).tooltip()`): a no-op;
// - the tooltip component of the platform (`frappe.ui.Tooltip`, the `tooltip` option of the buttons): never shown;
// - the tooltips of the shell (`data-bo-tip`): hidden in CSS (_components.scss).
(function () {
	const strip = (el) => {
		const title = el.getAttribute("title");
		if (title === null) return;
		// SVG <title> children are not attributes; an <iframe>/<abbr> title is content, kept as the label
		if (title && !el.hasAttribute("aria-label") && !el.hasAttribute("aria-labelledby")) {
			el.setAttribute("aria-label", title);
		}
		el.removeAttribute("title");
	};
	const sweep = (root) => {
		if (root.nodeType !== 1) return;
		if (root.hasAttribute("title")) strip(root);
		root.querySelectorAll("[title]").forEach(strip);
	};

	if ($.fn && $.fn.tooltip) {
		const noop = function () {
			return this;
		};
		noop.Constructor = $.fn.tooltip.Constructor;
		$.fn.tooltip = noop;
	}

	const silence_component = () => {
		const T = frappe.ui && frappe.ui.Tooltip;
		if (T && !T.prototype.bo_silenced) {
			T.prototype.schedule = function () {};
			T.prototype.show = function () {};
			T.prototype.bo_silenced = true;
		}
	};

	const start = () => {
		silence_component();
		sweep(document.body);
		new MutationObserver((records) => {
			for (const r of records) {
				if (r.type === "attributes") strip(r.target);
				else r.addedNodes.forEach(sweep);
			}
		}).observe(document.body, {
			subtree: true,
			childList: true,
			attributes: true,
			attributeFilter: ["title"],
		});
	};
	if (document.body) start();
	else document.addEventListener("DOMContentLoaded", start);
})();
