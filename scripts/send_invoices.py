"""Email demo invoice PDFs into Mailpit, one email per invoice, from the vendor's address.

Run:  .venv/bin/python scripts/send_invoices.py data/demo/live
      .venv/bin/python scripts/send_invoices.py data/demo/overnight --delay 1
Needs Mailpit:  docker run -d --name mailpit -p 8025:8025 -p 1025:1025 axllent/mailpit
"""
import argparse
import json
import smtplib
import time
from email.message import EmailMessage
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
AP_INBOX = "ap@harborridge.local"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="folder of invoice PDFs, e.g. data/demo/live")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1025)
    ap.add_argument("--delay", type=float, default=3.0, help="seconds between emails (for a live demo feel)")
    args = ap.parse_args()

    vendors = json.loads((DATA / "reference" / "vendors.json").read_text())
    pdfs = sorted(Path(args.folder).glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs in {args.folder}")

    with smtplib.SMTP(args.host, args.port) as smtp:
        for i, pdf in enumerate(pdfs):
            # file names look like 02_bolt_INV-B-5520.pdf
            _, vendor_key, number = pdf.stem.split("_", 2)
            v = vendors[vendor_key]
            msg = EmailMessage()
            msg["From"] = f"{v['name']} <{v['email']}>"
            msg["To"] = AP_INBOX
            msg["Subject"] = f"Invoice {number} from {v['name']}"
            msg.set_content(f"Hello,\n\nPlease find attached invoice {number}.\n\nRegards,\n{v['name']} Accounts")
            msg.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf", filename=f"{number}.pdf")
            smtp.send_message(msg)
            print(f"sent {number} from {v['name']}")
            if i < len(pdfs) - 1:
                time.sleep(args.delay)


if __name__ == "__main__":
    main()
