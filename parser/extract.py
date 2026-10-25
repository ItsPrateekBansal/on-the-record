"""Invoice Watchdog — PDF/text -> JSON via the local model (Ollama).
Used at ingest: a PDF becomes JSON before it ever reaches the watcher,
so the watcher only ever sees JSON. Stdlib only.
"""

import json
import re
import urllib.request

PROMPT = """Extract the invoice as JSON only, no other text.
Schema: {{"invoice_no": str, "vendor": str, "po": str or null,
"date": str or null, "total": number,
"lines": [{{"sku": str, "qty": number, "unit_price": number,
"unit": "unit" or "box", "description": str}}]}}
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


def _call_model(text: str, model: str,
                host: str = "http://localhost:11434") -> dict:
    body = json.dumps({"model": model,
                       "prompt": PROMPT.format(text=text),
                       "stream": False}).encode()
    req = urllib.request.Request(
        host + "/api/generate", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        out = json.loads(resp.read())["response"]
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
