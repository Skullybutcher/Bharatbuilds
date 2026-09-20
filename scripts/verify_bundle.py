#!/usr/bin/env python3
"""verify_bundle.py — independently verify a ProcessPatch governance bundle.

    python scripts/verify_bundle.py <bundle.json> [more.json ...]

Zero dependencies, standard library only — anyone holding a downloaded
*-governance-bundle.json can check, entirely offline:

  1. the bundle seal: bundle_sha256 is the sha256 of the bundle content with
     the bundle_sha256 key removed, canonicalized exactly as the producer did
     (sorted keys, compact separators);
  2. the certificate self-hash: certificate_sha256 over the certificate with
     its own hash key removed (sorted keys, default separators — the two
     producers canonicalize differently and this script follows each one).

It refuses to guess: a tampered byte, a missing seal, or an unknown bundle kind
is FAILed and named. Exit 0 only if every file passes.
"""
from __future__ import annotations

import hashlib
import json
import sys

BUNDLE_KIND = "processpatch-governance-bundle"


def sha(obj) -> str:
    """The certificate producer's exact canonicalization (default separators)."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _seal_of(content: dict) -> str:
    """The bundle producer's exact canonicalization (compact separators)."""
    blob = json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(blob).hexdigest()


def verify(path: str) -> tuple[bool, list[str]]:
    """(ok, report lines) for one bundle file."""
    notes: list[str] = []
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except OSError as e:
        return False, [f"unreadable: {e}"]
    except json.JSONDecodeError as e:
        return False, [f"not valid JSON: {e}"]
    if not isinstance(doc, dict):
        return False, ["top level is not a JSON object"]

    kind = doc.get("kind")
    if kind != BUNDLE_KIND:
        return False, [f"not a governance bundle (kind={kind!r}, expected {BUNDLE_KIND!r})"]

    build = doc.get("build") or {}
    notes.append(f"build:      {build.get('build_id', '?')} ({build.get('status', '?')})")
    notes.append(f"approvals:  {len(doc.get('approvals') or [])} on record")
    notes.append(f"audit rows: {len(doc.get('audit') or [])}")

    ok = True
    claimed = doc.pop("bundle_sha256", None)
    if not claimed:
        return False, notes + ["FAIL: no bundle_sha256 present — unsealed bundle"]
    recomputed = _seal_of(doc)
    if recomputed != claimed:
        ok = False
        notes.append(f"FAIL: bundle seal mismatch\n      claimed    {claimed}\n      recomputed {recomputed}\n      content was modified after export")
    else:
        notes.append(f"seal:       OK ({claimed[:16]}…)")

    cert = doc.get("certificate") or {}
    cert_claimed = cert.pop("certificate_sha256", None)
    if cert_claimed is None:
        notes.append("cert:       no self-hash present (older format) — skipped")
    else:
        cert_recomputed = sha(cert)
        if cert_recomputed != cert_claimed:
            ok = False
            notes.append(f"FAIL: certificate self-hash mismatch\n      claimed    {cert_claimed}\n      recomputed {cert_recomputed}\n      certificate fields were modified after issuance")
        else:
            notes.append(f"cert:       OK ({cert_claimed[:16]}…)")
    cert["certificate_sha256"] = cert_claimed
    doc["bundle_sha256"] = claimed
    return ok, notes


def main(argv: list[str]) -> int:
    paths = [a for a in argv[1:] if a not in ("-h", "--help")]
    if not paths:
        print(__doc__)
        return 2
    all_ok = True
    for p in paths:
        ok, notes = verify(p)
        all_ok &= ok
        verdict = "PASS" if ok else "FAIL"
        print(f"\n{verdict}  {p}")
        for line in notes:
            print(f"  {line}")
    print("\nALL BUNDLES VERIFIED" if all_ok else "\nVERIFICATION FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
