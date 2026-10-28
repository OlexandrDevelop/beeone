# Copyright (c) 2026 beeone authors
# License: MIT. See LICENSE

"""Print format constants: styles and macros for Jinja templates."""

STYLE = """<style>
.ua-form { font-size: 12px; color: #111; }
.ua-form h2 { font-size: 16px; margin: 0 0 4px; }
.ua-form .meta { margin-bottom: 10px; }
.ua-form table { width: 100%; border-collapse: collapse; margin: 8px 0; }
.ua-form th, .ua-form td { border: 1px solid #333; padding: 3px 6px; }
.ua-form th { background: #eee; text-align: center; }
.ua-form td.n, .ua-form th.n { text-align: right; white-space: nowrap; }
.ua-form .total { text-align: right; margin: 2px 0; }
.ua-form .sign { margin-top: 28px; }
.ua-form .sign td { border: 0; padding: 14px 6px 0; }
.ua-form .ref { color: #777; font-size: 10px; margin-top: 6px; }
.ua-form table.plain th, .ua-form table.plain td { border: 0; background: none; text-align: left; }
.ua-form td.logo { width: 90px; }
.ua-form td.logo img { max-height: 60px; max-width: 90px; }
.ua-form .cancel { color: #b00; font-weight: bold; }
.ua-form .words { margin: 6px 0; }
.ua-form .cut { border-top: 1px dashed #333; margin: 18px 0 10px; }
</style>"""

MACROS = """{% macro party(label, p) %}<div>{{ label }}: <b>{{ (p.title or "")|e }}</b>{% if p.edrpou %}, код ЄДРПОУ {{ p.edrpou|e }}{% endif %}{% if p.ipn %}, ІПН {{ p.ipn|e }}{% endif %}{% if p.legal_address %}, {{ p.legal_address|e }}{% endif %}{% if p.phone %}, тел. {{ p.phone|e }}{% endif %}</div>{% endmacro %}
{% macro bank(b) %}{% if b and b.iban %}<div>Р/р {{ b.iban|e }}{% if b.bank_name %}, {{ b.bank_name|e }}{% endif %}{% if b.mfo %}, МФО {{ b.mfo|e }}{% endif %}</div>{% endif %}{% endmacro %}
{% macro head(title) %}<table class="plain"><tr><td class="logo">{% if org.logo %}<img src="{{ org.logo|e }}">{% endif %}</td>
<td><h2>{{ title }}</h2>{% if doc.docstatus == 2 %}<div class="cancel">Скасовано</div>{% endif %}</td></tr></table>{% endmacro %}
{% macro sign(left, right) %}<table class="sign"><tr><td>{{ left }}</td><td>Директор ________________ {{ (org.director_name or "")|e }}</td>
<td>Головний бухгалтер ________________ {{ (org.accountant_name or "")|e }}</td><td>{{ right }}</td></tr></table><div>М.П.</div>{% endmacro %}
{% macro money(value, currency) %}{{ uk_money(value) }} {{ "грн" if (not currency or currency == "UAH") else currency|e }}{% endmacro %}
"""
