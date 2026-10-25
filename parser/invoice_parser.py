"""Invoice Watchdog — invoice parser.

Turns the raw dict the watcher hands over into a validated, canonical
Invoice. Tolerant of real-world mess (currency strings, aliased keys,
missing totals) but strict about the fields matching depends on.
Stdlib only.

Usage:
    from parser.invoice_parser import parse_invoice, parse_invoice_file
    invoice = parse_invoice(raw_dict)   # raises ParseError on bad input
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


class ParseError(ValueError):
    """Raised when an invoice cannot be parsed into a valid Invoice."""


@dataclass
class Line:
    sku: str
    qty: float
    unit_price: float
    description: str = ""

    @property
    def line_total(self) -> float:
        return round(self.qty * self.unit_price, 2)


@dataclass
class Invoice:
    invoice_no: str
    vendor: str
    po: str | None
    date: str | None
    total: float
    lines: list[Line]
    warnings: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


# Key aliases seen across vendors' invoice formats.
_INVOICE_ALIASES = {
    "invoice_no": ("invoice_no", "invoice_number", "invoice_id", "inv_no"),
    "vendor": ("vendor", "vendor_name", "supplier", "supplier_name"),
    "po": ("po", "po_number", "purchase_order", "po_no"),
    "total": ("total", "total_amount", "amount", "amount_due"),
    "lines": ("lines", "items", "line_items"),
    "date": ("date", "invoice_date", "issued_date"),
}
_LINE_ALIASES = {
    "sku": ("sku", "item", "code", "item_code", "product"),
    "qty": ("qty", "quantity", "count"),
    "unit_price": ("unit_price", "price", "rate", "unit_cost"),
    "description": ("description", "desc", "name"),
}

_MONEY_RE = re.compile(r"[^0-9.\-]")


def _pick(data: dict, aliases: tuple[str, ...]):
    """First present, non-None value under any alias, else None."""
    for key in aliases:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _money(value, what: str) -> float:
    """Parse a number that may arrive as '$4,850.00', '4850' or 4850."""
    if isinstance(value, bool):
        raise ParseError(f"{what}: not a number: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = _MONEY_RE.sub("", value.strip())
        if not cleaned or cleaned in ("-", ".", "-."):
            raise ParseError(f"{what}: not a number: {value!r}")
        try:
            return float(cleaned)
        except ValueError:
            raise ParseError(f"{what}: not a number: {value!r}")
    raise ParseError(f"{what}: not a number: {value!r}")


def _qty(value, what: str) -> float:
    num = _money(value, what)
    if num < 0:
        raise ParseError(f"{what}: negative quantity: {value!r}")
    return num


def _parse_line(raw: dict, index: int) -> Line:
    if not isinstance(raw, dict):
        raise ParseError(f"line {index}: not an object: {raw!r}")
    sku = _pick(raw, _LINE_ALIASES["sku"])
    if sku is None or str(sku).strip() == "":
        raise ParseError(f"line {index}: missing sku")
    qty_raw = _pick(raw, _LINE_ALIASES["qty"])
    if qty_raw is None:
        raise ParseError(f"line {index} ({sku}): missing qty")
    price_raw = _pick(raw, _LINE_ALIASES["unit_price"])
    if price_raw is None:
        raise ParseError(f"line {index} ({sku}): missing unit_price")
    desc = _pick(raw, _LINE_ALIASES["description"])
    return Line(
        sku=str(sku).strip(),
        qty=_qty(qty_raw, f"line {index} ({sku}) qty"),
        unit_price=_money(price_raw, f"line {index} ({sku}) unit_price"),
        description=str(desc) if desc is not None else "",
    )


def parse_invoice(data: dict) -> Invoice:
    """Validate and normalize one raw invoice dict."""
    if not isinstance(data, dict):
        raise ParseError(f"invoice is not an object: {data!r}")
    invoice_no = _pick(data, _INVOICE_ALIASES["invoice_no"])
    if invoice_no is None or str(invoice_no).strip() == "":
        raise ParseError("missing invoice_no")
    vendor = _pick(data, _INVOICE_ALIASES["vendor"])
    if vendor is None or str(vendor).strip() == "":
        raise ParseError(f"invoice {invoice_no}: missing vendor")
    po = _pick(data, _INVOICE_ALIASES["po"])
    date = _pick(data, _INVOICE_ALIASES["date"])
    lines_raw = _pick(data, _INVOICE_ALIASES["lines"])
    if not isinstance(lines_raw, list) or not lines_raw:
        raise ParseError(f"invoice {invoice_no}: missing or empty line items")
    lines = [_parse_line(item, i) for i, item in enumerate(lines_raw)]

    warnings: list[str] = []
    lines_sum = round(sum(ln.line_total for ln in lines), 2)
    total_raw = _pick(data, _INVOICE_ALIASES["total"])
    if total_raw is None:
        total = lines_sum
        warnings.append(f"total missing, computed from lines: {total:.2f}")
    else:
        total = _money(total_raw, f"invoice {invoice_no} total")
        if abs(total - lines_sum) > 0.01:
            warnings.append(
                f"total mismatch: stated {total:.2f}, lines sum {lines_sum:.2f}"
            )
    if po is None:
        warnings.append("no PO reference on invoice")
    return Invoice(
        invoice_no=str(invoice_no).strip(),
        vendor=str(vendor).strip(),
        po=str(po).strip() if po is not None else None,
        date=str(date) if date is not None else None,
        total=total,
        lines=lines,
        warnings=warnings,
        raw=data,
    )


def parse_invoice_file(path) -> Invoice:
    """Load a JSON invoice file and parse it."""
    path = Path(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ParseError(f"{path.name}: invalid JSON: {exc}")
    except OSError as exc:
        raise ParseError(f"{path.name}: unreadable: {exc}")
    try:
        return parse_invoice(data)
    except ParseError as exc:
        raise ParseError(f"{path.name}: {exc}")
