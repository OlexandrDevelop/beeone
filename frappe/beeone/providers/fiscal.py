# Copyright (c) 2026, beeone contributors
# License: MIT. See LICENSE

"""Contract of a fiscal device (cash register service) and its emulator (no network).

Money in a payload is in minor units (int, for example cents), quantity in thousandths (int).
Every method returns a dict or raises `FiscalError`; `FiscalOffline` means «stored, send later».
The credentials of a real provider are never read by the contract, never returned and never logged.

A second contract, `ReceiptImporter`, reads what a service already fiscalised (receipts and
shift reports) into one neutral form. It does not call the network: the answer of the service
is a parameter.
"""

from abc import ABC, abstractmethod

from frappe.beeone.providers import log_call
from frappe.utils import cint, now_datetime

MONEY_KEYS = ("sell_cash", "sell_card", "return_cash", "return_card", "service_in", "service_out")
COUNT_KEYS = ("receipts_count", "returns_count")
Z_KEYS = MONEY_KEYS + COUNT_KEYS

SELL, RETURN = "sell", "return"
CASH, CARD = "cash", "card"


class FiscalError(Exception):
	"""The provider refused the call."""


class FiscalOffline(Exception):
	"""The provider is not reachable: the document is stored and sent later."""


class FiscalDevice(ABC):
	name = ""

	@abstractmethod
	def open_shift(self) -> dict:
		"""{shift_id, opened_at}"""

	@abstractmethod
	def sell(self, receipt: dict) -> dict:
		"""{fiscal_code, fiscal_datetime, qr}. May raise FiscalOffline."""

	@abstractmethod
	def refund(self, receipt: dict) -> dict:
		"""Like `sell`, for a return."""

	@abstractmethod
	def service_in(self, amount: int) -> dict:
		"""{fiscal_code}"""

	@abstractmethod
	def service_out(self, amount: int) -> dict:
		"""{fiscal_code}"""

	@abstractmethod
	def x_report(self) -> dict:
		"""The Z keys (`Z_KEYS`) of the open shift."""

	@abstractmethod
	def close_shift(self) -> dict:
		"""The Z keys of the shift and `z_report_no`."""


class ReceiptImporter(ABC):
	"""Reads the answer of a service into neutral dicts."""

	name = ""

	@abstractmethod
	def normalize_receipt(self, raw: dict) -> dict:
		"""{id, kind: sell|return, shift, fiscal_code, fiscal_datetime (ISO text), total,
		payments: {cash, card}, goods: [{code, quantity, price}]}. Money in minor units, quantity in thousandths.
		Raises FiscalError for an unknown type or payment."""

	@abstractmethod
	def normalize_z_report(self, raw: dict) -> dict:
		"""{id, serial, opened_at, closed_at, sell_cash, sell_card, return_cash, return_card} (minor units)."""


class FiscalEmulator(FiscalDevice):
	"""In memory. `mode` is ok, error or offline (an offline sale still gets a code, like a stored receipt)."""

	name = "emulator"

	def __init__(self, number: str = "0001", mode: str = "ok", api_key: str | None = None):
		self.number = number
		self.mode = mode
		self._api_key = api_key  # kept only to show that it is never used or returned
		self.shift_no = 0
		self.shift_open = False
		self.seq = 0
		self.totals = dict.fromkeys(Z_KEYS, 0)

	def __repr__(self):
		return f"<FiscalEmulator {self.number}>"

	def _check(self, offline_ok=False):
		if self.mode == "error":
			raise FiscalError("Emulator: error on request")
		if self.mode == "offline":
			if offline_ok:
				raise FiscalOffline("Emulator: no connection")
			raise FiscalError("Emulator: no connection")

	def _need_shift(self):
		if not self.shift_open:
			raise FiscalError("The shift is not open")

	def _code(self):
		self._need_shift()
		self.seq += 1
		return f"EMU-{self.number}-{self.shift_no}-{self.seq:05d}"

	def open_shift(self):
		log_call(self.name, "open_shift", api_key=self._api_key)
		self._check()
		if self.shift_open:
			raise FiscalError("The shift is already open")
		self.shift_no += 1
		self.shift_open = True
		self.seq = 0
		self.totals = dict.fromkeys(Z_KEYS, 0)
		return {"shift_id": f"EMU-{self.number}-{self.shift_no}", "opened_at": now_datetime().isoformat(sep=" ")}

	def _receipt(self, receipt, prefix, count_key):
		self._check(offline_ok=True)
		code = self._code()
		pay = receipt.get("payments") or {}
		self.totals[f"{prefix}_cash"] += cint(pay.get(CASH))
		self.totals[f"{prefix}_card"] += cint(pay.get(CARD))
		self.totals[count_key] += 1
		total = cint(receipt.get("total"))
		return {
			"fiscal_code": code,
			"fiscal_datetime": now_datetime().isoformat(sep=" "),
			"qr": f"emulator://{self.number}/{code}?sum={total}",
		}

	def sell(self, receipt):
		log_call(self.name, "sell", receipt=receipt, api_key=self._api_key)
		return self._receipt(receipt, "sell", "receipts_count")

	def refund(self, receipt):
		log_call(self.name, "refund", receipt=receipt, api_key=self._api_key)
		return self._receipt(receipt, "return", "returns_count")

	def service_in(self, amount):
		self._check()
		code = self._code()
		self.totals["service_in"] += cint(amount)
		return {"fiscal_code": code}

	def service_out(self, amount):
		self._check()
		code = self._code()
		self.totals["service_out"] += cint(amount)
		return {"fiscal_code": code}

	def x_report(self):
		self._check()
		self._need_shift()
		return dict(self.totals)

	def close_shift(self):
		self._check()
		self._need_shift()
		result = dict(self.totals)
		result["z_report_no"] = f"EMU-Z-{self.number}-{self.shift_no}"
		self.shift_open = False
		return result


class EmulatorImporter(ReceiptImporter):
	"""Takes the neutral form as the service answer, checks it and returns it."""

	name = "emulator"

	def normalize_receipt(self, raw):
		kind = raw.get("kind")
		if kind not in (SELL, RETURN):
			raise FiscalError(f"Receipt {raw.get('id')}: unknown type {kind}")
		payments = {CASH: cint((raw.get("payments") or {}).get(CASH)), CARD: cint((raw.get("payments") or {}).get(CARD))}
		return {**raw, "kind": kind, "total": cint(raw.get("total")), "payments": payments, "goods": raw.get("goods") or []}

	def normalize_z_report(self, raw):
		out = {key: raw.get(key) for key in ("id", "serial", "opened_at", "closed_at")}
		out.update({key: cint(raw.get(key)) for key in ("sell_cash", "sell_card", "return_cash", "return_card")})
		return out
