"""REST client of a beeone site: the public resource API and whitelisted methods, as a given user."""
import json
from dataclasses import dataclass, field

import requests

MISSING_MARK = "FEATURE MISSING"

# Words of a server error that mean "this Python function / module is not there".
METHOD_MISSING = ("AttributeError", "ModuleNotFoundError", "ImportError", "Failed to get method", "No module named")

_NOT_COPIED = ("name", "creation", "modified", "owner", "modified_by", "docstatus", "idx", "doctype")
_NOT_COPIED_ROW = ("name", "parent", "creation", "modified", "owner", "modified_by")


class FeatureMissing(AssertionError):
    """The DocType, API method or report the test needs does not exist yet. A failure, not an error."""

    def __init__(self, what):
        super().__init__(f"{MISSING_MARK}: {what}")
        self.what = what


class ApiError(Exception):
    def __init__(self, resp):
        self.status = resp.status_code
        self.text = resp.text
        try:
            body = resp.json()
        except Exception:
            body = {}
        self.exc_type = body.get("exc_type", "") or ""
        msgs = []
        try:
            for m in json.loads(body.get("_server_messages", "[]") or "[]"):
                try:
                    msgs.append(json.loads(m).get("message", ""))
                except Exception:
                    msgs.append(str(m))
        except Exception:
            pass
        if body.get("exception"):
            msgs.append(str(body["exception"]))
        self.message = " | ".join(msgs) or resp.text[:500]
        super().__init__(f"HTTP {self.status} {self.exc_type}: {self.message[:800]}")


@dataclass
class Report:
    columns: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    totals: dict = None


_admin_sessions = {}
_exists_cache = {}


def _admin_session(base, password):
    if base not in _admin_sessions:
        s = requests.Session()
        r = s.post(base + "/api/method/login", json={"usr": "Administrator", "pwd": password}, timeout=60)
        r.raise_for_status()
        _admin_sessions[base] = s
    return _admin_sessions[base]


def exists_as_admin(base, password, doctype, name):
    """Does the document exist, asked as Administrator (cached): feature detection, not test data."""
    key = (base, doctype, name)
    if key not in _exists_cache:
        s = _admin_session(base, password)
        _exists_cache[key] = s.get(f"{base}/api/resource/{doctype}/{name}", timeout=60).status_code == 200
    return _exists_cache[key]


class Api:
    """Client of one site. Subclass it and set BASE and ADMIN_PASSWORD (the defaults of an application suite).

    detect_missing: turn "the DocType / report / app method is not there" into FeatureMissing, detected by what
    the client asked for and never by the (localized) text of the server message. App methods are those whose
    dotted path starts with one of APP_METHOD_PREFIXES.
    """

    BASE = None
    ADMIN_PASSWORD = "admin"
    detect_missing = False
    APP_METHOD_PREFIXES = ()

    def __init__(self, user="Administrator", password=None, base=None):
        self.user = user
        self.base = base or self.BASE
        self.s = requests.Session()
        if user != "Guest":
            r = self.s.post(
                self.base + "/api/method/login", json={"usr": user, "pwd": password or self.ADMIN_PASSWORD},
                timeout=60,
            )
            if r.status_code != 200:
                raise ApiError(r)

    # raw
    def request(self, method, path, **kw):
        kw.setdefault("timeout", 300)
        return self.s.request(method, self.base + path, **kw)

    # existence checks as administrator (feature detection)
    def _exists_as_admin(self, doctype, name):
        return exists_as_admin(self.base, self.ADMIN_PASSWORD, doctype, name)

    def doctype_exists(self, doctype):
        return self._exists_as_admin("DocType", doctype)

    def _ok(self, r, doctype=None, method=None, report=None):
        """Return the JSON body or raise FeatureMissing / ApiError."""
        if r.status_code < 400:
            return r.json()
        err = ApiError(r)
        if self.detect_missing:
            if doctype and r.status_code in (403, 404, 417, 500) and not self.doctype_exists(doctype):
                raise FeatureMissing(f"DocType «{doctype}» does not exist")
            if method and method.startswith(tuple(self.APP_METHOD_PREFIXES)) and any(
                w in r.text for w in METHOD_MISSING
            ):
                raise FeatureMissing(f"API method {method} does not exist")
            if report and not self._exists_as_admin("Report", report):
                raise FeatureMissing(f"report «{report}» does not exist")
        raise err

    # resource API
    def get_doc(self, doctype, name):
        r = self.request("GET", f"/api/resource/{doctype}/{name}")
        return self._ok(r, doctype=doctype)["data"]

    def exists(self, doctype, name):
        r = self.request("GET", f"/api/resource/{doctype}/{name}")
        if r.status_code == 200:
            return True
        if not self.detect_missing:
            return False
        if r.status_code == 404:
            if not self.doctype_exists(doctype):
                raise FeatureMissing(f"DocType «{doctype}» does not exist")
            return False
        self._ok(r, doctype=doctype)
        return False

    def get_list(self, doctype, filters=None, fields=None, order_by=None, limit=0):
        params = {"limit_page_length": limit or 100000, "fields": json.dumps(fields or ["name"])}
        if filters is not None:
            params["filters"] = json.dumps(filters)
        if order_by:
            params["order_by"] = order_by
        return self._ok(self.request("GET", f"/api/resource/{doctype}", params=params), doctype=doctype)["data"]

    def insert(self, doctype, **doc):
        return self._ok(self.request("POST", f"/api/resource/{doctype}", json=doc), doctype=doctype)["data"]

    def update(self, doctype, name, **values):
        return self._ok(self.request("PUT", f"/api/resource/{doctype}/{name}", json=values), doctype=doctype)["data"]

    def delete(self, doctype, name):
        return self._ok(self.request("DELETE", f"/api/resource/{doctype}/{name}"), doctype=doctype)

    # any whitelisted method
    def call(self, method, /, http="POST", **kw):
        doctype = None
        if method.startswith("frappe.client."):
            doc = kw.get("doc")
            doctype = kw.get("doctype") or (doc.get("doctype") if isinstance(doc, dict) else None)
        if http == "GET":
            r = self.request("GET", f"/api/method/{method}", params=kw)
        else:
            r = self.request("POST", f"/api/method/{method}", json=kw)
        return self._ok(r, doctype=doctype, method=method).get("message")

    # documents
    def submit(self, doctype, name):
        doc = self.get_doc(doctype, name)
        return self.call("frappe.client.submit", doc=doc)

    def cancel(self, doctype, name):
        return self.call("frappe.client.cancel", doctype=doctype, name=name)

    def insert_submit(self, doctype, **doc):
        d = self.insert(doctype, **doc)
        return self.submit(doctype, d["name"])

    def amend(self, doctype, name, **changes):
        old = self.get_doc(doctype, name)
        new = {k: v for k, v in old.items() if k not in _NOT_COPIED}
        for k, v in list(new.items()):
            if isinstance(v, list):
                new[k] = [{kk: vv for kk, vv in row.items() if kk not in _NOT_COPIED_ROW} for row in v]
        new["amended_from"] = name
        new.update(changes)
        return self.insert(doctype, **new)

    def count(self, doctype, filters=None):
        return self.call("frappe.client.get_count", doctype=doctype, filters=filters or {})

    # make_* returns an unsaved document
    def make(self, method, source_name, **options):
        return self.call(method, source_name=source_name, **options)

    def make_insert(self, method, source_name, submit=False, **changes):
        doc = self.make(method, source_name)
        doc.update(changes)
        saved = self.insert(doc["doctype"], **{k: v for k, v in doc.items() if k != "doctype"})
        return self.submit(saved["doctype"], saved["name"]) if submit else saved

    # reports
    def report(self, report_name, **filters):
        r = self.request(
            "POST", "/api/method/frappe.desk.query_report.run", json={"report_name": report_name, "filters": filters}
        )
        msg = self._ok(r, report=report_name).get("message") or {}
        rows = list(msg.get("result") or [])
        totals = None
        if rows and isinstance(rows[-1], dict) and rows[-1].get("is_total_row"):
            totals = rows.pop()
        return Report(columns=msg.get("columns") or [], rows=[x for x in rows if isinstance(x, dict)], totals=totals)
