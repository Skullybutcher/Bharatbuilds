#!/usr/bin/env python3
"""Archive debug/parked builds so the console shows the demo, not the war.

    python scripts/demo_cleanup.py <api-url> <email> <password> [--apply] [--keep BUILD-ID ...]

Default policy: archive every build that is NOT activated (PATCH_ACTIVE/ACTIVE)
and every DRAFT-*. That is exactly the debug residue from the gate war — drafts
never mutate by design, and parked builds are half-driven attempts. Archiving is
NON-DESTRUCTIVE: evidence stays readable, resume still works, the audit log gets
a BUILD_ARCHIVED event, and /unarchive brings anything back.

Dry-run unless --apply. Nothing is ever deleted: this is a governance product,
and an agent that deletes evidence to make a screenshot look nice would be the
wrong tool.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

KEEP_STATUSES = {"PATCH_ACTIVE", "ACTIVE"}


def req(url: str, data: bytes | None = None, headers: dict | None = None):
    r = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def region_of(api: str) -> str:
    """https://<id>.execute-api.<region>.amazonaws.com/<stage> -> <region>"""
    import re
    m = re.search(r"execute-api\.([a-z0-9-]+)\.amazonaws", api)
    if not m:
        print(f"cannot read the region out of {api!r}", file=sys.stderr)
        raise SystemExit(1)
    return m.group(1)


def login(api: str, email: str, password: str) -> dict:
    _, cfg = req(f"{api}/auth/config")
    region = region_of(api)
    body = json.dumps({"AuthFlow": "USER_PASSWORD_AUTH", "ClientId": cfg["client_id"],
                       "AuthParameters": {"USERNAME": email, "PASSWORD": password}}).encode()
    st, tok = req(f"https://cognito-idp.{region}.amazonaws.com/", data=body,
                  headers={"Content-Type": "application/x-amz-json-1.1",
                           "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth"})
    if st != 200 or "AuthenticationResult" not in tok:
        print(f"login failed (HTTP {st}): {json.dumps(tok)[:200]}", file=sys.stderr)
        raise SystemExit(2)
    return {"Authorization": f"Bearer {tok['AuthenticationResult']['IdToken']}"}


def main() -> int:
    ap = argparse.ArgumentParser(description="Archive non-activated builds (non-destructive).")
    ap.add_argument("api", help="API base URL, e.g. https://xxxx.execute-api.ap-south-1.amazonaws.com/prod")
    ap.add_argument("email")
    ap.add_argument("password")
    ap.add_argument("--apply", action="store_true", help="actually archive (default: dry run)")
    ap.add_argument("--keep", action="append", default=[], help="build id to keep visible (repeatable)")
    args = ap.parse_args()

    auth = login(args.api, args.email, args.password)
    ah = {**auth, "Content-Type": "application/json"}
    print(f"auth OK as {args.email}")

    st, payload = req(f"{args.api}/builds?include_archived=1", headers=auth)
    if st != 200:
        print(f"GET /builds failed (HTTP {st})", file=sys.stderr)
        return 3
    rows = payload.get("builds", [])
    keep = set(args.keep)

    targets, kept = [], []
    for b in rows:
        bid, status = b.get("build_id", ""), b.get("status", "")
        if bid in keep or status in KEEP_STATUSES or b.get("archived"):
            kept.append(b)
        else:
            targets.append(b)

    print(f"\n{len(rows)} builds on record — {len(kept)} kept, {len(targets)} to archive")
    for b in kept:
        print(f"  KEEP     {b.get('build_id'):<26} {b.get('status')}")
    for b in targets:
        print(f"  ARCHIVE  {b.get('build_id'):<26} {b.get('status')}")

    if not targets:
        print("\nnothing to do"); return 0
    if not args.apply:
        print("\ndry run — re-run with --apply to archive these")
        return 0

    failures = 0
    for b in targets:
        bid = b["build_id"]
        st, out = req(f"{args.api}/builds/{bid}/archive", data=b"{}", headers=ah)
        ok = st == 200 and out.get("archived") is True
        print(f"  {'archived' if ok else f'FAILED (HTTP {st})'}: {bid}")
        failures += 0 if ok else 1

    st, after = req(f"{args.api}/builds", headers=auth)
    visible = [b.get("build_id") for b in after.get("builds", [])]
    print(f"\nconsole now shows {len(visible)}: {', '.join(visible)}")
    print("reversible: POST /builds/{id}/unarchive")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
