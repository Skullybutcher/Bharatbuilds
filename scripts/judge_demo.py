"""Judge demo — scripted, verifiable walkthrough (demo/judge_script.md).

Runs the live local API (auth off) and verifies each beat of the 4-minute
script prints what the script promises. Exit 0 = every beat holds; a non-zero
exit means the demo would embarrass you on stage — fix before recording.

Usage: python scripts/judge_demo.py [--port 8010]
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class Beat:
    def __init__(self, num, title, claim):
        self.num, self.title, self.claim = num, title, claim

    def __str__(self):
        return f"BEAT {self.num}: {self.title}\n  claim: {self.claim}"


def _req(port, method, path, body=None):
    r = urllib.request.Request(f"http://localhost:{port}{path}", method=method,
                               data=json.dumps(body).encode() if body is not None else None,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8010)
    args = ap.parse_args()
    port = args.port
    beats: list[Beat] = []
    failures: list[str] = []

    def verify(beat: Beat, cond: bool, detail: str):
        beats.append(beat)
        mark = "OK " if cond else "FAIL"
        print(f"[{mark}] {beat}\n    -> {detail}\n")
        if not cond:
            failures.append(f"{beat.num}: {detail}")

    proc = subprocess.Popen([sys.executable, "-m", "services.api.server", str(port)],
                            cwd=str(ROOT), env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            time.sleep(0.25)
            try:
                if _req(port, "GET", "/health")[0] == 200:
                    break
            except Exception:
                continue

        # Beat 1 — the stale portal wrongs a real person
        b1 = Beat(1, "The stale portal", "CGPA 7.80 applicant is ELIGIBLE under Policy V2 "
                                        "but the portal INELIGIBLE — drift harms a real person")
        _, portal = _req(port, "GET", "/portal?cgpa=7.8&domain=research_grant")
        verify(b1, portal["expected"]["eligible"] is True and portal["actual"]["eligible"] is False,
               f"expected eligible={portal['expected']['eligible']} actual={portal['actual']['eligible']}")

        # Beat 2 — compile the amendment
        b2 = Beat(2, "Compile the amendment", "One click produces a verified build with "
                                              "witnesses, a localized patch, and passing regression tests")
        _, build = _req(port, "GET", "/demo/canonical?domain=research_grant")
        v = build.get("validation", {})
        verify(b2, bool(build.get("witnesses")) and v.get("passed") == v.get("total")
               and v.get("total", 0) >= 12,
               f"build {build['build_id']} status={build['status']} "
               f"witnesses={len(build.get('witnesses', []))} tests={v.get('passed')}/{v.get('total')}")

        # Beat 3 — a witness is a person, not a number
        w0 = (build.get("witnesses") or [{}])[0]
        b3 = Beat(3, "Meet the person who proves the bug", "Witness W-001 shows expected vs "
                                                           "actual paths for one concrete case")
        verify(b3, w0.get("witness_id") == "W-001" and bool(w0.get("case")) and bool(w0.get("trace_expected")),
               f"{w0.get('witness_id')} kind={w0.get('kind')} case={json.dumps(w0.get('case', {}))[:90]}")

        # Beat 4 — impact is evidence-backed
        b4 = Beat(4, "Impact from evidence, not estimates", "Blast radius counts trace to "
                                                            "witnesses and a labeled synthetic cohort")
        imp = build.get("impact", {})
        verify(b4, bool(imp.get("artifacts", {}).get("nodes_affected")) and
               (imp.get("test_cohort", {}).get("cohort_size", 0) > 0),
               f"nodes={imp.get('artifacts', {}).get('nodes_affected')} "
               f"cohort_n={imp.get('test_cohort', {}).get('cohort_size')}")

        # Beat 5 — governance: hash-bound approval, distinct humans
        b5 = Beat(5, "Merge protection + human gates", "Reviewer (Gate 1/2) and admin (Gate 3) "
                                                       "are separate humans; approval binds exact hashes")
        bid = build["build_id"]
        for r in build.get("new_rules", []):
            _req(port, "POST", f"/builds/{bid}/rules/{r['rule_id']}/accept", {"reason": "gate1"})
        _req(port, "POST", f"/builds/{bid}/patch/approve",
             {"reviewer": {"reviewer_id": "reviewer@demo", "display_name": "Reviewer"},
              "reason": "gate2", "role": "PROCEDURE_OWNER"})
        code, appr = _req(port, "GET", f"/builds/{bid}/approvals")
        codes = [a.get("decision") for a in appr.get("approvals", [])]
        verify(b5, "APPROVE_CANDIDATE" in codes,
               f"approvals={codes} (Gate 3 activation requires pp-admins — see docs/auth.md)")

        # Beat 6 — runtime traces confirm the story
        b6 = Beat(6, "Runtime traces (real-world evidence)", "A trace of the real execution "
                                                             "disagrees with the stale procedure but matches the patch")
        _, tr = _req(port, "POST", "/traces", {
            "case": {"cgpa": 7.8, "amount": 0, "year": 3, "backlogs": 0, "category": "general",
                     "submission_date": "2026-09-28"},
            "outcome": {"eligible": True}, "source": "runtime-log"})
        _, cmp = _req(port, "GET", f"/builds/{bid}/trace-compare")
        row = next((x for x in cmp.get("results", []) if x["trace_id"] == tr["trace_id"]), {})
        verify(b6, row.get("vs_stale", {}).get("status") == "DISAGREE"
               and row.get("vs_patched", {}).get("status") == "AGREE",
               f"vs_stale={row.get('vs_stale', {}).get('status')} vs_patched={row.get('vs_patched', {}).get('status')}")

        print("=" * 60)
        if failures:
            print(f"DEMO NOT READY — {len(failures)} beat(s) failed:")
            for f in failures:
                print("  " + f)
            return 1
        print(f"ALL {len(beats)} BEATS VERIFIED — safe to record (script: demo/judge_script.md)")
        return 0
    finally:
        proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
