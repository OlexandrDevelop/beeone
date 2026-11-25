# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Help pages of the apps and the search the assistant answers from (works without a model too).

An app gives its pages with the hook `beeone_ai_help` = ["app.module.pages"]; `pages()` returns dicts:
	{"id": str, "title": str, "text": markdown, "kind": "guide"|"reference", "doctypes": [DocType, ...]}
A guide is written for the user (how to do a task); a reference describes an object; an overview lists many objects.
Pages are split into sections by their `##` headings; the search is BM25 over the words cut to their stems
(the first 5 letters are enough for Ukrainian and English endings), the title counts three times.
"""

import math
import re
from collections import Counter

import frappe

TOKEN = re.compile(r"[0-9a-zA-Zа-яА-ЯіїєґІЇЄҐʼ'’]+")
STEM = 5
MAX_SECTION = 2400
K1, B = 1.4, 0.75
KIND_BOOST = {"guide": 1.6, "reference": 1.0, "overview": 0.6}
STOP = {
	"і", "й", "та", "в", "у", "на", "з", "із", "зі", "до", "по", "за", "як", "що", "це", "чи", "не", "для", "від", "або",
	"а", "але", "ж", "же", "ще", "все", "мені", "мене", "я", "ми", "ви", "його", "її", "їх", "який", "яка", "яке", "які",
	"the", "a", "an", "of", "to", "in", "on", "and", "or", "is", "how", "what", "do", "i", "for", "with", "be",
	"зробити", "можна", "треба", "потрібно", "програмі", "програма",
}

_index = {}


def words(text):
	out = []
	for w in TOKEN.findall((text or "").lower().replace("’", "ʼ").replace("'", "ʼ")):
		w = w.strip("ʼ")
		if len(w) < 2 or w in STOP:
			continue
		out.append(w[:STEM])
	return out


def pages():
	out = []
	for path in frappe.get_hooks("beeone_ai_help") or []:
		try:
			out.extend(frappe.get_attr(path)() or [])
		except Exception:
			frappe.log_error(title=f"AI help source {path}")
	return out


def split_sections(page):
	"""Sections of a page: (heading, text); the text before the first `##` belongs to the title."""
	parts = re.split(r"(?m)^##\s+", page.get("text") or "")
	head = parts[0]
	sections = []
	if head.strip():
		sections.append(("", head))
	for part in parts[1:]:
		heading, _, body = part.partition("\n")
		sections.append((heading.strip(), "## " + part))
	out = []
	for heading, text in sections:
		text = text.strip()
		while len(text) > MAX_SECTION:
			cut = text.rfind("\n", 0, MAX_SECTION)
			cut = cut if cut > MAX_SECTION // 2 else MAX_SECTION
			out.append((heading, text[:cut]))
			text = text[cut:].strip()
		if text:
			out.append((heading, text))
	return out


def build_index():
	docs = []
	all_pages = pages()
	for page in all_pages:
		title = page.get("title") or page.get("id")
		for i, (heading, text) in enumerate(split_sections(page)):
			terms = words(title) * 3 + words(heading) * 2 + words(text)
			docs.append(
				{
					"page": page.get("id"),
					"title": title,
					"heading": heading,
					"text": text,
					"kind": page.get("kind") or "reference",
					"doctypes": page.get("doctypes") or [],
					"part": i,
					"tf": Counter(terms),
					"len": len(terms) or 1,
				}
			)
	df = Counter()
	for d in docs:
		df.update(d["tf"].keys())
	n = len(docs) or 1
	return {
		"docs": docs,
		"idf": {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()},
		"avg": sum(d["len"] for d in docs) / n,
		"pages": {p.get("id"): p for p in all_pages},
	}


def index():
	key = frappe.local.site
	if key not in _index:
		_index[key] = build_index()
	return _index[key]


def clear_index():
	_index.pop(frappe.local.site, None)


def search(query, limit=6, doctype=None):
	"""The best sections for the query: a page gives at most two of them."""
	idx = index()
	terms = words(query)
	if not terms and not doctype:
		return []
	scored = []
	for d in idx["docs"]:
		score = 0.0
		for t in terms:
			f = d["tf"].get(t)
			if f:
				score += idx["idf"][t] * f * (K1 + 1) / (f + K1 * (1 - B + B * d["len"] / idx["avg"]))
		if doctype and doctype in d["doctypes"]:
			score = score * 1.5 + 2
		if score > 0:
			scored.append((score * KIND_BOOST.get(d["kind"], 1.0), d))
	scored.sort(key=lambda x: -x[0])
	out, per_page = [], Counter()
	for score, d in scored:
		if per_page[d["page"]] >= 2:
			continue
		per_page[d["page"]] += 1
		out.append(
			{
				"page": d["page"],
				"title": d["title"],
				"section": d["heading"],
				"kind": d["kind"],
				"text": d["text"],
				"score": round(score, 2),
			}
		)
		if len(out) >= limit:
			break
	return out


def page(page_id):
	p = index()["pages"].get(page_id)
	if not p:
		return None
	return {"id": page_id, "title": p.get("title"), "kind": p.get("kind") or "reference", "text": p.get("text") or ""}
