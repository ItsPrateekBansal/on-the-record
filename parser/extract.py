"""Invoice Watchdog — PDF/text -> JSON via the local model (Ollama).
Used at ingest: a PDF becomes JSON before it ever reaches the watcher,
so the watcher only ever sees JSON. Stdlib only.
"""

import json
import re
import urllib.error
import urllib.request

PROMPT = """Extract the invoice as JSON only, no other text.
Schema: {{"invoice_no": str, "vendor": str, "po": str or null,
"date": str or null, "total": number,
"lines": [{{"sku": str, "qty": number, "unit_price": number,
"unit": str or null, "description": str}}]}}
"sku": the item code only (like "BR-6204" or "CS-PAL"), never the description.
"unit": copy the value of the line's unit-of-measure column (headed "Unit" or
"UOM") exactly as printed, for example "box (12)", "carton", "roll", "case".
Do not shorten it, convert it or guess what it contains. Sizes or dimensions
in the description (like "48x40" or "500 g") are not units. If the invoice has
no unit-of-measure column, use null.
If a field is missing, use null. Lines must not be empty.
Invoice text:
{text}"""


def extract_text(pdf_path: str) -> str:
    try:
        import pdfplumber
    except ImportError:
        raise RuntimeError("pdfplumber not installed: pip install pdfplumber")
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def _generate(host: str, payload: dict) -> str:
    req = urllib.request.Request(
        host + "/api/generate", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())["response"]


def _call_model(text: str, model: str,
                host: str = "http://localhost:11434") -> dict:
    payload = {"model": model, "prompt": PROMPT.format(text=text),
               "stream": False, "think": False}  # thinking: minutes instead of seconds
    try:
        out = _generate(host, payload)
    except urllib.error.HTTPError as exc:
        if exc.code != 400:  # 400: this model has no thinking switch; ask again without it
            raise
        payload.pop("think")
        out = _generate(host, payload)
    match = re.search(r"\{.*\}", out, re.S)
    if not match:
        raise ValueError(f"model returned no JSON: {out[:200]!r}")
    return json.loads(match.group(0))


def extract_invoice(text: str, model: str) -> dict:
    """Model -> dict, with one retry. Raises on failure, never guesses."""
    last_exc = None
    for _ in range(2):
        try:
            data = _call_model(text, model)
            if isinstance(data, dict) and data.get("lines"):
                return data
            last_exc = ValueError(f"bad extraction: {str(data)[:200]!r}")
        except Exception as exc:
            last_exc = exc
    raise ValueError(f"extraction failed after retry: {last_exc}")
