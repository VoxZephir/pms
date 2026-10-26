"""The `/caviarder` page: a PDF sent from the browser comes back redacted
(`redact.py`, `docs/caviardage.md`). The original only passes through a
temporary folder -- never inbox/, where it would be ingested -- and the
copy is kept in output/caviarde/, served from there for download."""

from __future__ import annotations

import datetime as dt
import re
import tempfile
from pathlib import Path

from flask import abort, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge

from ... import redact
from . import api, payload

RECENT = 8
SAFE = re.compile(r"[^\w.\-]+")


def _copies() -> list[dict]:
    if not redact.OUTPUT.is_dir():
        return []
    files = sorted(redact.OUTPUT.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)[:RECENT]
    return [{"file": p.name, "size": p.stat().st_size,
             "at": dt.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="minutes"),
             "url": f"/caviarde/{p.name}"} for p in files]


@api.route("/api/caviarder")
def redaction():
    return payload({"available": redact.available(), "folder": str(redact.OUTPUT), "copies": _copies()})


@api.route("/api/caviarder", methods=["POST"])
def redact_file():
    if not redact.available():
        return payload({"error": "PyMuPDF n'est pas installé : lancer caviarder.bat une fois, "
                                 "ou `uv sync --extra web --inexact`."}), 503
    try:
        sent = request.files.get("pdf")
    except RequestEntityTooLarge:
        return payload({"error": "Fichier trop lourd (plus de 25 Mo)."}), 413
    if sent is None or not sent.filename:
        return payload({"error": "Aucun fichier choisi."}), 400
    content = sent.read()
    if not content.startswith(b"%PDF"):
        return payload({"error": f"{sent.filename} n'est pas un PDF."}), 400
    stem = SAFE.sub("-", Path(sent.filename).stem).strip("-") or "document"
    target = redact.OUTPUT / f"{stem}-caviarde.pdf"
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / f"{stem}.pdf"
        source.write_bytes(content)
        try:
            report = redact.redact(source, target, redact.terms(request.form.get("also")),
                                   redact.terms(request.form.get("spare")))
        except RuntimeError as exc:  # the read-back found a removed passage still there
            target.unlink(missing_ok=True)
            return payload({"error": f"{sent.filename} : {exc}"}), 422
        except Exception as exc:  # a PDF PyMuPDF cannot read, or a bug: said, never a half copy
            target.unlink(missing_ok=True)
            return payload({"error": f"{sent.filename} n'a pas pu être caviardé ({type(exc).__name__}). "
                                     "Aucune copie n'a été gardée."}), 422
    kinds = report.by_kind()
    names = sorted({f.text for f in report.found if f.kind != "IBAN"})
    return payload({
        "file": target.name, "url": f"/caviarde/{target.name}", "pages": report.pages,
        "count": len(report.found),
        "kinds": [{"kind": k, "count": n} for k, n in sorted(kinds.items(), key=lambda kv: -kv[1])],
        # What left, never in clear.
        "names": [redact.mask(n) for n in names],
    })


@api.route("/caviarde/<name>")
def redacted_copy(name: str):
    path = (redact.OUTPUT / name).resolve()
    if path.parent != redact.OUTPUT.resolve() or path.suffix != ".pdf" or not path.is_file():
        abort(404)
    return send_file(path, mimetype="application/pdf", as_attachment=True, download_name=name)
