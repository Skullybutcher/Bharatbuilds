#!/usr/bin/env python3
"""Live demo driver: compile a FRESH amendment, then drive all three gates.

    python scripts/demo_run.py <api-url> <email> <password>

Why fresh: the canonical demo policy is already compiled, and the product is
deliberately idempotent — re-submitting identical input returns the cached build
(READY_CACHED) and never reaches a gate. That is correct behaviour and a good
beat to *mention*, but it is not a pipeline demo. So this script rewrites the
CGPA threshold to a value that has not been compiled, walks the candidate list
until POST /builds reports no reuse, and then drives the real thing:

    POST /builds (deferred) -> POST /execute -> Step Functions compile
      -> Gate 1 (rule_review, only if extraction needs review)
      -> Gate 2 (patch_approval, APPROVE_CANDIDATE)
      -> Gate 3 (activation, APPROVE) -> ACTIVATE -> PATCH_ACTIVE
      -> governance bundle + witness coverage

Exit codes: 0 green, 1 usage/policy rewrite, 2 auth, 3 pipeline stage failure.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from demo_cleanup import login, region_of, req  # noqa: E402  (shared auth helpers)

# Thresholds tried in order until one has not been compiled yet.
CANDIDATES = [6.95, 6.85, 6.75, 6.65, 6.55, 6.45, 6.35, 6.25, 6.15, 6.05, 5.95, 5.85]
POLICY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "..", "demo", "research_grant", "policy_v2.md")


def say(msg: str) -> None:
    print(f"\n=== {msg} ===", flush=True)


def rewrite_policy(threshold: float) -> str:
    with open(POLICY_PATH, encoding="utf-8") as f:
        text = f.read()
    new, n = re.subn(r"CGPA >= [0-9.]+\.", f"CGPA >= {threshold}.", text, count=1)
    if n != 1:
        print("could not find the CGPA threshold line in the demo policy", file=sys.stderr)
        raise SystemExit(1)
    # keep the provenance line honest about what changed
    new = new.replace("(Relaxed from 8.0.)", f"(Relaxed from 8.0; demo run {threshold}.)", 1)
    return new


def main() -> int:
    ap = argparse.ArgumentParser(description="Compile a fresh amendment and drive all gates.")
    ap.add_argument("api")
    ap.add_argument("email")
    ap.add_argument("password")
    ap.add_argument("--domain", default="research_grant")
    ap.add_argument("--timeout", type=int, default=240, help="seconds to wait per gate")
    args = ap.parse_args()

    auth = login(args.api, args.email, args.password)
    ah = {**auth, "Content-Type": "application/json"}
    say(f"signed in as {args.email}")

    # ---- pick a genuinely novel amendment ------------------------------------
    _, base = req(f"{args.api}/builds?include_archived=1", headers=auth)
    known = {b.get("build_id") for b in base.get("builds", [])}
    draft = None
    for threshold in CANDIDATES:
        policy = rewrite_policy(threshold)
        body = json.dumps({"domain": args.domain, "defer": True, "policy_text": policy}).encode()
        st, out = req(f"{args.api}/builds", data=body, headers=ah)
        if st != 200:
            print(f"POST /builds failed (HTTP {st}): {json.dumps(out)[:200]}", file=sys.stderr)
            return 3
        if out.get("idempotent_reuse"):
            print(f"  threshold {threshold}: already compiled — trying the next")
            continue
        draft = out["build_id"]
        print(f"  amendment accepted: CGPA >= {threshold}  ({draft})")
        break
    if not draft:
        print("every candidate threshold was already compiled", file=sys.stderr)
        return 1

    # ---- compile through Step Functions --------------------------------------
    say("compile (Step Functions)")
    st, ex = req(f"{args.api}/builds/{draft}/execute", data=b"{}", headers=ah)
    if st != 200 or not ex.get("executionArn"):
        print(f"/execute failed (HTTP {st}): {json.dumps(ex)[:200]}", file=sys.stderr)
        return 3
    arn = ex["executionArn"]
    print(f"  execution: {arn.split(':execution:')[-1]}")

    bid, deadline = None, time.time() + args.timeout
    while time.time() < deadline and not bid:
        time.sleep(3)
        _, lst = req(f"{args.api}/builds?include_archived=1", headers=auth)
        for b in lst.get("builds", []):
            if b.get("build_id", "").startswith("BUILD-") and b.get("build_id") not in known:
                bid = b["build_id"]
                break
    if not bid:
        print("no BUILD- document appeared — the execution died before persisting", file=sys.stderr)
        return 3
    print(f"  compiled: {bid}")

    def status() -> dict:
        return req(f"{args.api}/builds/{bid}", headers=auth)[1]

    def wait_for(ok: set, label: str) -> dict:
        end = time.time() + args.timeout
        cur = status()
        while time.time() < end:
            cur = status()
            if cur.get("status") in ok:
                return cur
            time.sleep(3)
        print(f"  {label}: timed out at {cur.get('status')}", file=sys.stderr)
        raise SystemExit(3)

    def resume(bod: dict, label: str) -> dict:
        end = time.time() + args.timeout
        while time.time() < end:
            st, r = req(f"{args.api}/builds/{bid}/resume", data=json.dumps(bod).encode(), headers=ah)
            if "no waiting callback" in json.dumps(r):
                print(f"  [{label}] gate not armed yet — retrying")
                time.sleep(3)
                continue
            if st != 200 or "error" in r:
                print(f"  [{label}] rejected (HTTP {st}): {json.dumps(r)[:220]}", file=sys.stderr)
                raise SystemExit(3)
            print(f"  [{label}] {json.dumps(r)[:200]}")
            return r
        print(f"  [{label}] gate never armed", file=sys.stderr)
        raise SystemExit(3)

    parked = wait_for({"NEEDS_REVIEW", "PATCH_VALIDATED", "NO_VALIDATED_PATCH"}, "park")
    print(f"  parked at: {parked.get('status')}")
    if parked.get("status") == "NO_VALIDATED_PATCH":
        print("  compile produced no valid patch — nothing to approve", file=sys.stderr)
        return 3

    if parked.get("status") == "NEEDS_REVIEW":
        say("Gate 1 — rule review (human decisions)")
        resume({"gate": "rule_review", "decisions": {},
                "reviewer": {"reviewer_id": args.email, "display_name": "demo"}}, "gate1")
        wait_for({"PATCH_VALIDATED"}, "post-gate-1")

    say("Gate 2 — patch approval")
    resume({"gate": "patch_approval", "decision": "APPROVE_CANDIDATE",
            "role": "PROCEDURE_OWNER",
            "reviewer": {"reviewer_id": args.email, "display_name": "demo"},
            "reason": "demo run"}, "gate2")

    say("Gate 3 — activation")
    resume({"gate": "activation", "decision": "APPROVE",
            "reviewer": {"reviewer_id": args.email, "display_name": "demo"},
            "reason": "demo run"}, "gate3")

    final = wait_for({"PATCH_ACTIVE", "ACTIVE"}, "activation")
    print(f"  activated: {final.get('status')}")

    # ---- evidence ------------------------------------------------------------
    say("evidence")
    _, bundle = req(f"{args.api}/builds/{bid}/governance-bundle", headers=auth)
    print(f"  governance bundle: {len(bundle.get('approvals', []))} approvals, "
          f"sha {str(bundle.get('bundle_sha256'))[:16]}")
    _, cov = req(f"{args.api}/builds/{bid}/coverage", headers=auth)
    n, f = cov.get("nodes", {}), cov.get("fields", {})
    print(f"  witness coverage: nodes {n.get('covered')}/{n.get('total')}, "
          f"fields {f.get('covered')}/{f.get('total')}")
    _, exd = req(f"{args.api}/executions/{arn}", headers=auth)
    print(f"  execution: {exd.get('status')}")

    say(f"DEMO RUN GREEN — {bid} compiled, approved twice, activated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
