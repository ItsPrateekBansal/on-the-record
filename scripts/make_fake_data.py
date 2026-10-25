"""Generate the fake Invoice Watchdog data set.

Run:  .venv/bin/python scripts/make_fake_data.py
Writes everything under data/. Safe to re-run (overwrites).
Every invoice is written twice: a PDF (for the local-model extraction story) and a JSON twin in the
format parser/invoice_parser.py reads (drop it into the inbox when PDF extraction isn't ready).
"""
import json
import shutil
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent / "data"
BUYER = {
    "name": "Harbor Ridge Manufacturing, Inc.",
    "address": "1200 Foundry Way, Oakland, CA 94607",
    "ap_email": "ap@harborridge.local",
}

# ---------------------------------------------------------------- vendors + contracts
# catalog: sku -> (description, contract unit, contract price, clause)
VENDORS = {
    "acme": {
        "name": "Acme Packaging Co.",
        "address": "88 Carton Ave, Stockton, CA 95203",
        "email": "billing@acmepackaging.local",
        "style": "A",
        "catalog": {
            "AC-1212": ("Corrugated shipping box 12x12x8", "unit", 1.20, "2.1"),
            "AC-TAPE": ("Packing tape roll, 2 in x 110 yd", "roll", 3.40, "2.2"),
            "AC-WRAP": ("Stretch wrap roll, 18 in x 1500 ft", "roll", 18.75, "2.3"),
        },
        "sections": [
            ("2", "Pricing", [
                ("2.1", "The unit price for SKU AC-1212 (corrugated shipping box 12x12x8) shall be $1.20 per unit."),
                ("2.2", "The unit price for SKU AC-TAPE (packing tape roll) shall be $3.40 per roll."),
                ("2.3", "The unit price for SKU AC-WRAP (stretch wrap roll) shall be $18.75 per roll."),
                ("2.4", "All prices in this Section 2 are fixed from January 1, 2026 through December 31, 2026 and include delivery to Buyer's Oakland facility."),
            ]),
        ],
    },
    "bolt": {
        "name": "Bolt Industrial Supply LLC",
        "address": "4410 Rivet Road, Fresno, CA 93725",
        "email": "invoices@boltindustrial.local",
        "style": "B",
        "catalog": {
            "BX-200": ("Stainless anchor bolt M16 x 200 mm", "unit", 12.00, "3.1"),
            "NT-080": ("Nylon lock nut M16", "unit", 2.40, "3.3"),
            "WS-016": ("Flat washer M16, stainless", "unit", 0.85, "3.4"),
        },
        "sections": [
            ("2", "Quality and Inspection", [
                ("2.1", "All goods shall conform to ISO 3506 and shall be free from defects in material and workmanship."),
                ("2.2", "Buyer may inspect goods within ten (10) business days of delivery and reject nonconforming goods."),
            ]),
            ("3", "Pricing", [
                ("3.1", "Unit price for SKU BX-200 shall be $12.00 per unit, fixed through Dec 31, 2026."),
                ("3.2", "For any single purchase order of more than 2,000 units of SKU BX-200, the unit price shall instead be $11.40 per unit."),
                ("3.3", "Unit price for SKU NT-080 shall be $2.40 per unit."),
                ("3.4", "Unit price for SKU WS-016 shall be $0.85 per unit."),
                ("3.5", "Supplier may not increase any price in this Section 3 without a written amendment signed by both parties."),
            ]),
        ],
    },
    "coastal": {
        "name": "Coastal Supply Co.",
        "address": "17 Harbor Blvd, Long Beach, CA 90802",
        "email": "ar@coastalsupply.local",
        "style": "C",
        "catalog": {
            "CS-PAL": ("Heavy-duty wooden pallet 48x40", "unit", 60.00, "4.1"),
            "CS-CRT": ("Stackable plastic crate, 60 L", "unit", 22.50, "4.2"),
        },
        "sections": [
            ("2", "Ordering", [
                ("2.1", "Supplier shall ship only the quantities stated on Buyer's purchase order. Goods shipped in excess of the purchase order quantity will not be paid for."),
            ]),
            ("3", "Delivery", [
                ("3.1", "Delivery is FOB Buyer's facility. Risk of loss passes on delivery."),
            ]),
            ("4", "Pricing", [
                ("4.1", "Heavy-duty wooden pallets 48x40 (SKU CS-PAL) are priced at sixty dollars ($60.00) each."),
                ("4.2", "Stackable plastic crates, 60 L (SKU CS-CRT) are priced at twenty-two dollars and fifty cents ($22.50) each."),
                ("4.3", "Prices are firm for the term of this Agreement."),
            ]),
        ],
    },
    "delta": {
        "name": "Delta Office Solutions",
        "address": "905 Market St, Suite 300, San Francisco, CA 94103",
        "email": "billing@deltaoffice.local",
        "style": "A",
        "catalog": {
            "DO-PPR": ("Copy paper, letter, case of 10 reams", "case", 45.00, "2.1"),
            "DO-TNR": ("Toner cartridge, black, high yield", "unit", 85.00, "2.2"),
            "DO-PEN": ("Ballpoint pens, box of 50", "box", 9.50, "2.3"),
        },
        "sections": [
            ("2", "Pricing", [
                ("2.1", "Copy paper (SKU DO-PPR) is $45.00 per case of ten reams."),
                ("2.2", "Black high-yield toner cartridges (SKU DO-TNR) are $85.00 each."),
                ("2.3", "Ballpoint pens (SKU DO-PEN) are $9.50 per box of 50."),
            ]),
        ],
    },
    "evergreen": {
        "name": "Evergreen Parts Inc.",
        "address": "3021 Timber Lane, Sacramento, CA 95815",
        "email": "accounts@evergreenparts.local",
        "style": "B",
        "catalog": {
            "BR-6204": ("Deep groove ball bearing 6204-2RS", "unit", 11.50, "2.4"),
            "GR-500": ("Lithium grease tube, 500 g", "tube", 7.80, "2.2"),
        },
        "sections": [
            ("2", "Pricing", [
                ("2.1", "Prices in this Section are in US dollars and exclude sales tax; Buyer holds a resale exemption certificate."),
                ("2.2", "Lithium grease tubes, 500 g (SKU GR-500), are priced at $7.80 per tube."),
                ("2.3", "Prices are fixed for calendar year 2026."),
                ("2.4", "Deep groove ball bearings 6204-2RS (SKU BR-6204) are priced at $11.50 per unit. Bearings are packed and invoiced in boxes of 12 units; the price per box therefore shall not exceed twelve times the unit price."),
            ]),
        ],
    },
}

COMMON_SECTIONS = [
    ("1", "Scope and Term", [
        ("1.1", "This Master Supply Agreement (the \"Agreement\") governs all purchases by Buyer from Supplier between January 1, 2026 and December 31, 2026."),
        ("1.2", "Each purchase is made by a written purchase order (\"PO\") issued by Buyer. Supplier shall reference the PO number on every invoice."),
    ]),
]
# Closing sections, numbered right after each vendor's own sections (see contract_sections).
TAIL_SECTIONS = [
    ("Invoicing and Payment", [
        "Payment terms are net thirty (30) days from receipt of a correct invoice.",
        "Supplier shall issue one invoice per shipment and shall not invoice the same goods more than once. A re-issued invoice must clearly state that it replaces an earlier invoice.",
        "Buyer may dispute any invoice amount within thirty (30) days of receipt by written notice to Supplier. Undisputed amounts shall be paid on time.",
    ]),
    ("Confidentiality", [
        "The prices in this Agreement are confidential information of both parties and shall not be disclosed to any third party.",
    ]),
]


def contract_sections(vendor):
    """All sections of a vendor's contract, numbered 1, 2, 3, ... with no gaps."""
    own = COMMON_SECTIONS + VENDORS[vendor]["sections"]
    nums = [int(n) for n, _, _ in own]
    assert nums == list(range(1, len(own) + 1)), f"{vendor}: sections {nums}"
    tail = [(str(len(own) + i + 1), heading, [(f"{len(own) + i + 1}.{k + 1}", text) for k, text in enumerate(texts)])
            for i, (heading, texts) in enumerate(TAIL_SECTIONS)]
    return own + tail


def duplicate_clause(vendor):
    """The 'no invoicing the same goods twice' clause: second clause of the Invoicing section."""
    return next(f"{n}.2" for n, heading, _ in contract_sections(vendor) if heading == "Invoicing and Payment")


# ---------------------------------------------------------------- purchase orders + invoices
# line = (sku, qty, unit_price, invoice_unit_label)
def L(sku, qty, price, unit=None):
    return {"sku": sku, "qty": qty, "unit_price": price, "unit": unit}


# expect: status PASS | FAIL | NEEDS_REVIEW, the main failed check, and the amount at risk.
# The audit() oracle below recomputes all of this from the documents and must agree.
INVOICES = [
    # ---- live demo (sent during the pitch). Bolt goes first: it is the centerpiece.
    dict(set="live", file="01_bolt_INV-B-5520.pdf", vendor="bolt", number="INV-B-5520", date="2026-10-23", po="PO-7750",
         lines=[L("BX-200", 500, 13.44)],
         expect=dict(status="FAIL", check="contract_price", at_risk=720.00,
                     proof="The invoice matches PO-7750 exactly ($13.44 x 500), so a PO match passes. Contract clause 3.1 "
                           "says $12.00 per unit. 500 x ($13.44 - $12.00) = $720.00 of leakage.")),
    dict(set="live", file="02_coastal_INV-CS-0912.pdf", vendor="coastal", number="INV-CS-0912", date="2026-10-23", po="PO-7781",
         lines=[L("CS-PAL", 100, 60.00)],
         expect=dict(status="FAIL", check="po_quantity", at_risk=1200.00,
                     proof="Billed 100 pallets, PO-7781 line 1 ordered 80 and receipt GR-4432 received 80. "
                           "20 x $60.00 = $1,200.00. Contract 2.1: excess quantities will not be paid.")),
    dict(set="live", file="03_acme_INV-1047.pdf", vendor="acme", number="INV-1047", date="2026-10-23", po="PO-7701",
         lines=[L("AC-1212", 1100, 1.20)],
         expect=dict(status="FAIL", check="po_quantity", at_risk=360.00,
                     proof="PO-7701 ordered 2,000 boxes. Previous transaction INV-1043 already billed 1,200, so only 800 "
                           "remain. This invoice bills 1,100: 300 x $1.20 = $360.00 over the PO. Each invoice alone "
                           "looks fine; only the history shows it.")),
    dict(set="live", file="05_delta_INV-D-3270A.pdf", vendor="delta", number="INV-D-3270A", date="2026-10-22", po="PO-7695",
         lines=[L("DO-PPR", 15, 45.00), L("DO-TNR", 2, 85.00), L("DO-PEN", 6, 9.50)],
         expect=dict(status="FAIL", check="duplicate", at_risk=902.00,
                     proof="Same vendor, same PO-7695 and same $902.00 as previous transaction INV-D-3270, already "
                           "paid on 2026-10-16; the number differs only by a trailing 'A'. Contract 3.2: no "
                           "invoicing the same goods twice.")),
    dict(set="live", file="04_delta_INV-D-3301.pdf", vendor="delta", number="INV-D-3301", date="2026-10-24", po="PO-7790",
         lines=[L("DO-PPR", 40, 45.00), L("DO-TNR", 6, 85.00)],
         expect=dict(status="PASS", check=None, at_risk=0.00,
                     proof="Prices match clauses 2.1 and 2.2; quantities match PO-7790 and its receipt.")),
    # ---- wifi-off demo
    dict(set="wifi_off", file="05_evergreen_INV-EV-208.pdf", vendor="evergreen", number="INV-EV-208", date="2026-10-24", po="PO-7802",
         lines=[L("BR-6204", 10, 150.00, "box (12)")],
         expect=dict(status="FAIL", check="contract_price", at_risk=120.00,
                     proof="Billed $150.00 per box of 12. Clause 2.4: $11.50 per unit, so max $138.00 per box. "
                           "10 x $12.00 = $120.00.")),
    # ---- overnight batch: 11 pass, 2 fail, 1 needs human review
    dict(set="overnight", file="o01_acme_INV-1048.pdf", vendor="acme", number="INV-1048", date="2026-10-20", po="PO-7760",
         lines=[L("AC-1212", 1500, 1.20), L("AC-WRAP", 10, 18.75)], expect=dict(status="PASS", check=None, at_risk=0.00)),
    dict(set="overnight", file="o02_bolt_INV-B-5498.pdf", vendor="bolt", number="INV-B-5498", date="2026-10-20", po="PO-7761",
         lines=[L("NT-080", 1000, 2.40), L("WS-016", 1000, 0.85)], expect=dict(status="PASS", check=None, at_risk=0.00)),
    dict(set="overnight", file="o03_delta_INV-D-3287.pdf", vendor="delta", number="INV-D-3287", date="2026-10-20", po="PO-7762",
         lines=[L("DO-PEN", 20, 9.50), L("DO-PPR", 10, 45.00)], expect=dict(status="PASS", check=None, at_risk=0.00)),
    dict(set="overnight", file="o04_evergreen_INV-EV-199.pdf", vendor="evergreen", number="INV-EV-199", date="2026-10-21", po="PO-7763",
         lines=[L("GR-500", 4, 93.60, "carton")],
         expect=dict(status="NEEDS_REVIEW", check="unit_of_measure", at_risk=0.00,
                     proof="Billed 4 cartons of grease at $93.60. Clause 2.2 prices tubes ($7.80 per tube) and the contract "
                           "never says how many tubes a carton holds, so the price cannot be verified. Not flagged as an "
                           "overcharge; sent to a person.")),
    dict(set="overnight", file="o05_coastal_INV-CS-0901.pdf", vendor="coastal", number="INV-CS-0901", date="2026-10-21", po="PO-7764",
         lines=[L("CS-CRT", 200, 22.50)], expect=dict(status="PASS", check=None, at_risk=0.00)),
    dict(set="overnight", file="o06_coastal_INV-CS-0897.pdf", vendor="coastal", number="INV-CS-0897", date="2026-10-21", po="PO-7765",
         lines=[L("CS-PAL", 125, 64.80)],
         expect=dict(status="FAIL", check="contract_price", at_risk=600.00,
                     proof="Billed $64.80 per pallet, clause 4.1 says $60.00 (8% over). 125 x $4.80 = $600.00.")),
    dict(set="overnight", file="o07_bolt_INV-B-5503.pdf", vendor="bolt", number="INV-B-5503", date="2026-10-21", po="PO-7766",
         lines=[L("BX-200", 250, 12.00)], expect=dict(status="PASS", check=None, at_risk=0.00)),
    dict(set="overnight", file="o08_evergreen_INV-EV-201.pdf", vendor="evergreen", number="INV-EV-201", date="2026-10-22", po="PO-7767",
         lines=[L("BR-6204", 5, 138.00, "box (12)")], expect=dict(status="PASS", check=None, at_risk=0.00,
         proof="$138.00 per box of 12 = 12 x $11.50, matches clause 2.4. Shows correct box pricing passes.")),
    dict(set="overnight", file="o09_acme_INV-1051.pdf", vendor="acme", number="INV-1051", date="2026-10-22", po="PO-7768",
         lines=[L("AC-TAPE", 400, 3.40)],
         expect=dict(status="FAIL", check="po_quantity", at_risk=680.00,
                     proof="Billed 400 rolls, PO-7768 ordered 200. 200 x $3.40 = $680.00.")),
    dict(set="overnight", file="o10_delta_INV-D-3292.pdf", vendor="delta", number="INV-D-3292", date="2026-10-22", po="PO-7769",
         lines=[L("DO-TNR", 4, 85.00)], expect=dict(status="PASS", check=None, at_risk=0.00)),
    dict(set="overnight", file="o11_acme_INV-1053.pdf", vendor="acme", number="INV-1053", date="2026-10-22", po="PO-7770",
         lines=[L("AC-WRAP", 24, 18.75)], expect=dict(status="PASS", check=None, at_risk=0.00)),
    dict(set="overnight", file="o12_coastal_INV-CS-0905.pdf", vendor="coastal", number="INV-CS-0905", date="2026-10-23", po="PO-7771",
         lines=[L("CS-PAL", 45, 60.00)], expect=dict(status="PASS", check=None, at_risk=0.00)),
    dict(set="overnight", file="o13_bolt_INV-B-5511.pdf", vendor="bolt", number="INV-B-5511", date="2026-10-23", po="PO-7772",
         lines=[L("WS-016", 2000, 0.85), L("NT-080", 500, 2.40)], expect=dict(status="PASS", check=None, at_risk=0.00)),
    dict(set="overnight", file="o14_delta_INV-D-3296.pdf", vendor="delta", number="INV-D-3296", date="2026-10-23", po="PO-7773",
         lines=[L("DO-PPR", 25, 45.00)], expect=dict(status="PASS", check=None, at_risk=0.00)),
]

# PO quantities/prices where they differ from the invoice (the traps); others mirror the invoice.
PO_OVERRIDES = {
    # Bolt: the PO carries the same wrong price as the invoice, so only the contract check catches it.
    "PO-7750": [L("BX-200", 500, 13.44)],
    "PO-7763": [L("GR-500", 48, 7.80)],
    "PO-7701": [L("AC-1212", 2000, 1.20)],
    "PO-7781": [L("CS-PAL", 80, 60.00)],
    "PO-7802": [L("BR-6204", 120, 11.50)],
    "PO-7765": [L("CS-PAL", 125, 60.00)],
    "PO-7768": [L("AC-TAPE", 200, 3.40)],
    "PO-7767": [L("BR-6204", 60, 11.50)],
}

# Goods receipts (what the warehouse received). Default: the full PO quantity.
# Coastal: set 80 -> 75 to show PO 80 / received 75 / billed 100 (at risk becomes $1,500; update its expect).
RECEIPT_OVERRIDES = {"PO-7781": ("GR-4432", 80)}

# Units the contract itself defines. Anything else (e.g. "carton") cannot be converted -> NEEDS_REVIEW.
CONVERSIONS = {("BR-6204", "box (12)"): 12}     # Evergreen clause 2.4: boxes of 12 units
VOLUME_TIERS = {"BX-200": (2000, 11.40, "3.2")}  # Bolt clause 3.2: more than 2,000 units -> $11.40
QUANTITY_CLAUSES = {"coastal": "2.1"}           # "goods shipped in excess ... will not be paid for"

# Previous transactions: invoices already audited and paid, saved in each company's transactions/ folder.
# INV-1043 already billed 1,200 of PO-7701's 2,000 boxes (see live INV-1047).
# INV-D-3270 is re-sent as INV-D-3270A (live duplicate).
HISTORY = [
    dict(number="INV-1043", vendor="acme", date="2026-10-14", po="PO-7701", paid_on="2026-10-20",
         lines=[L("AC-1212", 1200, 1.20)]),
    dict(number="INV-1039", vendor="acme", date="2026-09-28", po="PO-7688", paid_on="2026-10-08",
         lines=[L("AC-1212", 1050, 1.20)]),
    dict(number="INV-B-5471", vendor="bolt", date="2026-09-30", po="PO-7690", paid_on="2026-10-12",
         lines=[L("BX-200", 400, 12.00)]),
    dict(number="INV-CS-0880", vendor="coastal", date="2026-10-02", po="PO-7693", paid_on="2026-10-15",
         lines=[L("CS-PAL", 60, 60.00)]),
    dict(number="INV-D-3270", vendor="delta", date="2026-10-06", po="PO-7695", paid_on="2026-10-16",
         lines=[L("DO-PPR", 15, 45.00), L("DO-TNR", 2, 85.00), L("DO-PEN", 6, 9.50)]),
    dict(number="INV-EV-190", vendor="evergreen", date="2026-10-07", po="PO-7697", paid_on="2026-10-17",
         lines=[L("BR-6204", 4, 138.00, "box (12)")]),
]
PO_DATES = {"PO-7701": "2026-10-05"}
RESULT_FOLDERS = {"PASS": "success", "FAIL": "discrepancy", "NEEDS_REVIEW": "needs_review"}



# ---------------------------------------------------------------- helpers
def money(x):
    return f"${x:,.2f}"


def line_total(line):
    return round(line["qty"] * line["unit_price"], 2)


def invoice_total(lines):
    return round(sum(line_total(l) for l in lines), 2)


def unit_label(vendor, line):
    return line["unit"] or VENDORS[vendor]["catalog"][line["sku"]][1]


def clause_text(vendor, number):
    for _, _, clauses in contract_sections(vendor):
        for cnum, text in clauses:
            if cnum == number:
                return text
    raise KeyError(f"{vendor} clause {number}")


# ---------------------------------------------------------------- reference audit (the answer key)
def contract_terms(vendor, sku, qty_units):
    _, _, price, clause = VENDORS[vendor]["catalog"][sku]
    tier = VOLUME_TIERS.get(sku)
    if tier and qty_units > tier[0]:
        return tier[1], tier[2]
    return price, clause


def normalize(vendor, line):
    """Invoice line in contract units as (qty, unit_price), or None if the contract doesn't define the unit."""
    label = unit_label(vendor, line)
    if label == VENDORS[vendor]["catalog"][line["sku"]][1]:
        return line["qty"], line["unit_price"]
    factor = CONVERSIONS.get((line["sku"], label))
    if factor is None:
        return None
    return line["qty"] * factor, round(line["unit_price"] / factor, 4)


def audit(inv, po, receipt, history):
    """Transaction (PO + receipt, net of what earlier invoices on the PO already billed), commercial
    (contract) and historical (duplicate of a previous transaction)."""
    vendor, total = inv["vendor"], invoice_total(inv["lines"])
    previous = [h for h in history if h["vendor"] == vendor and h["po"] == inv["po"]]
    billed_before = {}
    for h in previous:
        for hl in h["lines"]:
            billed_before[hl["sku"]] = billed_before.get(hl["sku"], 0) + normalize(vendor, hl)[0]
    po_lines = {l["sku"]: l for l in po["lines"]}
    received = {l["sku"]: l["qty_received"] for l in receipt["lines"]}
    checks = {k: "PASS" for k in ("po_price", "po_quantity", "receipt_quantity", "contract_price", "duplicate")}
    clauses, payable, review = [], 0.0, False
    for line in inv["lines"]:
        norm = normalize(vendor, line)
        if norm is None:
            review = True
            for k in ("po_price", "po_quantity", "receipt_quantity", "contract_price"):
                checks[k] = "NEEDS_REVIEW"
            clauses.append(VENDORS[vendor]["catalog"][line["sku"]][3])
            continue
        qty, price = norm
        cprice, clause = contract_terms(vendor, line["sku"], qty)
        clauses.append(clause)
        pl = po_lines[line["sku"]]
        prior = billed_before.get(line["sku"], 0)
        po_left, received_left = max(0, pl["qty"] - prior), max(0, received[line["sku"]] - prior)
        if abs(price - pl["unit_price"]) > 0.005:
            checks["po_price"] = "FAIL"
        if qty > po_left:
            checks["po_quantity"] = "FAIL"
            if vendor in QUANTITY_CLAUSES:
                clauses.append(QUANTITY_CLAUSES[vendor])
        if qty > received_left:
            checks["receipt_quantity"] = "FAIL"
        if price > cprice + 0.005:
            checks["contract_price"] = "FAIL"
        payable += min(qty, po_left, received_left) * min(price, cprice)

    dup = next((h for h in previous if invoice_total(h["lines"]) == total), None)
    if dup:
        checks["duplicate"] = "FAIL"
        clauses.append(duplicate_clause(vendor))

    def layer(*names):
        vals = [checks[n] for n in names]
        return "FAIL" if "FAIL" in vals else "NEEDS_REVIEW" if "NEEDS_REVIEW" in vals else "PASS"

    status = "FAIL" if "FAIL" in checks.values() else "NEEDS_REVIEW" if review else "PASS"
    at_risk = total if dup else 0.0 if review else round(total - payable, 2)
    return {
        "status": status,
        "at_risk": at_risk,
        "amount_under_review": total if status == "NEEDS_REVIEW" else 0.0,
        "layers": {
            "transaction": {"status": layer("po_price", "po_quantity", "receipt_quantity"),
                            "checks": {k: checks[k] for k in ("po_price", "po_quantity", "receipt_quantity")}},
            "commercial": {"status": layer("contract_price"), "checks": {"contract_price": checks["contract_price"]}},
            "historical": {"status": layer("duplicate"), "checks": {"duplicate": checks["duplicate"]},
                           "matched_transaction": dup["number"] if dup else None},
        },
        "result_folder": f"results/{RESULT_FOLDERS[status]}",
        "evidence": {
            "po": f"companies/{vendor}/pos/{po['po_number']}.json",
            "receipt": f"companies/{vendor}/receipts/{receipt['receipt_id']}.json",
            "previous_transactions": [f"companies/{vendor}/transactions/{h['number']}.json" for h in previous],
            "contract": f"companies/{vendor}/contract.pdf",
            "clauses": {c: clause_text(vendor, c) for c in dict.fromkeys(clauses)},
        },
    }


STYLES = getSampleStyleSheet()
SMALL = ParagraphStyle("small", parent=STYLES["Normal"], fontSize=9, leading=11)
BODY = ParagraphStyle("body", parent=STYLES["Normal"], fontSize=10, leading=13)


def table_style(header_bg):
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), header_bg),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ])


def write_invoice(path, vendor_key, number, date, po, lines, note=None):
    v = VENDORS[vendor_key]
    style = v["style"]
    doc = SimpleDocTemplate(str(path), pagesize=letter, topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    s = []
    total = invoice_total(lines)

    if style == "A":
        s.append(Paragraph(f"<b>{v['name']}</b>", STYLES["Title"]))
        s.append(Paragraph(f"{v['address']} · {v['email']}", SMALL))
        s.append(Spacer(1, 12))
        s.append(Paragraph("<b>INVOICE</b>", STYLES["Heading2"]))
        meta = [["Invoice Number", number], ["Invoice Date", date], ["Purchase Order", po], ["Terms", "Net 30"]]
        head = ["SKU", "Description", "Qty", "Unit", "Unit Price", "Amount"]
        rows = [[l["sku"], v["catalog"][l["sku"]][0], f"{l['qty']:,}", unit_label(vendor_key, l),
                 money(l["unit_price"]), money(line_total(l))] for l in lines]
        widths = [0.9 * inch, 2.6 * inch, 0.6 * inch, 0.8 * inch, 0.9 * inch, 1.0 * inch]
        bg = colors.HexColor("#dde6f0")
    elif style == "B":
        s.append(Paragraph(f"<para alignment='right'><b>{v['name'].upper()}</b><br/>{v['address']}<br/>{v['email']}</para>", BODY))
        s.append(Spacer(1, 18))
        s.append(Paragraph("Tax Invoice / Bill", STYLES["Heading2"]))
        meta = [["Bill No.", number], ["Date of Issue", date], ["Your Order #", po], ["Payment", "30 days net"]]
        head = ["Item Code", "Item", "Qty Shipped", "UOM", "Rate", "Line Total"]
        rows = [[l["sku"], v["catalog"][l["sku"]][0], f"{l['qty']:,}", unit_label(vendor_key, l),
                 money(l["unit_price"]), money(line_total(l))] for l in lines]
        widths = [0.9 * inch, 2.3 * inch, 1.0 * inch, 0.8 * inch, 0.8 * inch, 1.0 * inch]
        bg = colors.HexColor("#e8e8e8")
    else:  # "C": SKU folded into description, different labels
        s.append(Paragraph(f"<b>{v['name']}</b> — {v['address']}", BODY))
        s.append(Paragraph(f"Remit to: {v['email']}", SMALL))
        s.append(Spacer(1, 14))
        s.append(Paragraph(f"<b>Invoice #{number}</b>", STYLES["Heading2"]))
        meta = [["Dated", date], ["Customer PO", po], ["Due", "Net 30"]]
        head = ["#", "Description", "Quantity", "Each", "Total"]
        rows = [[str(i + 1), f"{v['catalog'][l['sku']][0]} ({l['sku']})", f"{l['qty']:,}",
                 money(l["unit_price"]), money(line_total(l))] for i, l in enumerate(lines)]
        widths = [0.4 * inch, 3.6 * inch, 0.9 * inch, 0.9 * inch, 1.0 * inch]
        bg = colors.HexColor("#e6f0e6")

    s.append(Table(meta, colWidths=[1.4 * inch, 2.4 * inch],
                   style=TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold")])))
    s.append(Spacer(1, 10))
    s.append(Paragraph(f"<b>Bill To:</b> {BUYER['name']}, {BUYER['address']}", SMALL))
    s.append(Spacer(1, 10))
    s.append(Table([head] + rows, colWidths=widths, style=table_style(bg)))
    s.append(Spacer(1, 8))
    s.append(Table([["Subtotal", money(total)], ["Sales tax (resale exempt)", money(0)], ["TOTAL DUE", money(total)]],
                   colWidths=[2.0 * inch, 1.2 * inch], hAlign="RIGHT",
                   style=TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
                                     ("LINEABOVE", (0, 2), (-1, 2), 0.8, colors.black), ("FONTSIZE", (0, 0), (-1, -1), 9)])))
    s.append(Spacer(1, 16))
    s.append(Paragraph(note or "Thank you for your business. Please reference the invoice number with your payment.", SMALL))
    doc.build(s)
    return total


def write_invoice_json(path, vendor_key, number, date, po, lines):
    """Structured twin of an invoice PDF, in the format parser/invoice_parser.py reads."""
    v = VENDORS[vendor_key]
    body = {"invoice_number": number, "vendor": v["name"], "po_number": po, "date": date,
            "total": invoice_total(lines),
            "lines": [{"sku": l["sku"], "description": v["catalog"][l["sku"]][0], "qty": l["qty"],
                       "unit": l["unit"], "unit_price": l["unit_price"]} for l in lines]}
    path.write_text(json.dumps(body, indent=2))


def write_contract(vendor_key):
    v = VENDORS[vendor_key]
    sections = contract_sections(vendor_key)
    pdf = ROOT / "companies" / vendor_key / "contract.pdf"
    txt = pdf.with_suffix(".txt")
    title = f"MASTER SUPPLY AGREEMENT — {v['name']}"
    intro = (f"This Agreement is made on January 1, 2026 between {BUYER['name']} (\"Buyer\") and "
             f"{v['name']}, {v['address']} (\"Supplier\").")
    lines_txt = [title, "", intro, ""]
    s = [Paragraph(title, STYLES["Heading1"]), Paragraph(intro, BODY), Spacer(1, 8)]
    for num, heading, clauses in sections:
        s.append(Paragraph(f"<b>{num}. {heading}</b>", STYLES["Heading3"]))
        lines_txt.append(f"{num}. {heading}")
        for cnum, text in clauses:
            s.append(Paragraph(f"{cnum} {text}", BODY))
            s.append(Spacer(1, 4))
            lines_txt.append(f"{cnum} {text}")
        lines_txt.append("")
    s += [Spacer(1, 18), Paragraph("Signed for Buyer: ____________________    Signed for Supplier: ____________________", SMALL)]
    SimpleDocTemplate(str(pdf), pagesize=letter).build(s)
    txt.write_text("\n".join(lines_txt))


# ---------------------------------------------------------------- main
def main():
    for sub in ["companies", "demo", "inbox", "results", "outbox", "reference"]:
        shutil.rmtree(ROOT / sub, ignore_errors=True)
    for d in ["demo/live", "demo/wifi_off", "demo/overnight", "inbox", "outbox",
              *(f"results/{f}" for f in RESULT_FOLDERS.values()),
              *(f"companies/{k}/{f}" for k in VENDORS for f in ("pos", "receipts", "transactions"))]:
        (ROOT / d).mkdir(parents=True, exist_ok=True)

    for key in VENDORS:
        write_contract(key)
    # lookup table the agent uses to find a company's folder, contract and SKU clauses
    index = {key: {"name": v["name"], "email": v["email"], "address": v["address"], "folder": f"companies/{key}",
                   "contract": "contract.pdf", "contract_text": "contract.txt",
                   "effective_from": "2026-01-01", "effective_to": "2026-12-31",
                   "skus": {sku: {"unit": c[1], "clause": c[3]} for sku, c in v["catalog"].items()}}
             for key, v in VENDORS.items()}
    (ROOT / "companies" / "index.json").write_text(json.dumps(index, indent=2))

    # POs: one per invoice, overrides for the traps
    pos = {}
    for inv in HISTORY + INVOICES:
        po = inv["po"]
        if po in pos:
            continue
        lines = PO_OVERRIDES.get(po, inv["lines"])
        pos[po] = {
            "po_number": po,
            "vendor_key": inv["vendor"],
            "vendor": VENDORS[inv["vendor"]]["name"],
            "date": PO_DATES.get(po, inv["date"]),
            "buyer": BUYER["name"],
            "lines": [{"line": i + 1, "sku": l["sku"], "description": VENDORS[inv["vendor"]]["catalog"][l["sku"]][0],
                       "qty": l["qty"], "unit": VENDORS[inv["vendor"]]["catalog"][l["sku"]][1],
                       "unit_price": l["unit_price"]} for i, l in enumerate(lines)],
        }
    for po, body in pos.items():
        (ROOT / "companies" / body["vendor_key"] / "pos" / f"{po}.json").write_text(json.dumps(body, indent=2))

    receipts = {}
    for i, (po, body) in enumerate(pos.items()):
        rid, qty = RECEIPT_OVERRIDES.get(po, (f"GR-{4401 + i}", None))
        receipts[po] = {
            "receipt_id": rid, "po_number": po, "vendor": body["vendor"], "date": body["date"],
            "lines": [{"sku": l["sku"], "qty_received": qty if qty is not None else l["qty"], "unit": l["unit"]}
                      for l in body["lines"]],
        }
        (ROOT / "companies" / body["vendor_key"] / "receipts" / f"{rid}.json").write_text(json.dumps(receipts[po], indent=2))

    for h in HISTORY:
        path = ROOT / "companies" / h["vendor"] / "transactions" / f"{h['number']}.json"
        write_invoice_json(path, h["vendor"], h["number"], h["date"], h["po"], h["lines"])
        body = json.loads(path.read_text())
        path.write_text(json.dumps(body | {"status": "PASS", "paid_on": h["paid_on"]}, indent=2))


    expected = []
    for inv in INVOICES:
        total = write_invoice(ROOT / "demo" / inv["set"] / inv["file"], inv["vendor"], inv["number"], inv["date"], inv["po"], inv["lines"])
        write_invoice_json((ROOT / "demo" / inv["set"] / inv["file"]).with_suffix(".json"),
                           inv["vendor"], inv["number"], inv["date"], inv["po"], inv["lines"])
        e, result = inv["expect"], audit(inv, pos[inv["po"]], receipts[inv["po"]], HISTORY)
        # the hand-written expectation and the computed audit must agree, or the data set has a mistake
        checks = {k: v for lay in result["layers"].values() for k, v in lay["checks"].items()}
        main_check_ok = e["check"] is None or e["check"] == "unit_of_measure" or checks[e["check"]] == "FAIL"
        if result["status"] != e["status"] or result["at_risk"] != e["at_risk"] or not main_check_ok:
            raise SystemExit(f"{inv['number']}: expected {e}, audit computed {result['status']} {result['at_risk']} {checks}")
        expected.append({"set": inv["set"], "file": inv["file"], "vendor": VENDORS[inv["vendor"]]["name"],
                         "invoice": inv["number"], "date": inv["date"], "po": inv["po"], "total": total,
                         "status": e["status"], "main_check": e["check"], **result, "proof": e.get("proof")})

    summary = {}
    for row in expected:
        s = summary.setdefault(row["set"], {"invoices": 0, "pass": 0, "fail": 0, "needs_review": 0,
                                            "at_risk": 0.0, "under_review": 0.0})
        s["invoices"] += 1
        s[row["status"].lower()] += 1
        s["at_risk"] = round(s["at_risk"] + row["at_risk"], 2)
        s["under_review"] = round(s["under_review"] + row["amount_under_review"], 2)
    (ROOT / "expected_results.json").write_text(json.dumps({"summary": summary, "invoices": expected}, indent=2))

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
