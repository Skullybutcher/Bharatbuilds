"""End-to-end test for the one-command local app (scripts/app.py).

Spawns the real runner on free ports with an isolated data dir and asserts the
full stack through its single origin: static shell, generated config.js, API
proxy, seeded demo state, CSV bulk ingest, and clean child reaping on shutdown.
This is the "make app" safety net: if it breaks, the local demo breaks.
"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
APP = ROOT / "scripts" / "app.py"


def _get(url: str, timeout: float = 30.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _post_json(url: str, body: dict):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _builds_list(base: str) -> list:
    _, _, body = _get(base + "/api/builds")
    d = json.loads(body)
    return d["builds"] if isinstance(d, dict) else d


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    port, bport = _free_port(), _free_port()
    data_dir = tmp_path_factory.mktemp("pp_app_data")
    env = {**os.environ, "PROCESSPATCH_STORAGE": "files",
           "PROCESSPATCH_DATA": str(data_dir)}
    proc = subprocess.Popen(
        [sys.executable, str(APP), "--no-open", "--port", str(port),
         "--backend-port", str(bport)],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True)
    base = f"http://127.0.0.1:{port}"
    ready = False
    for _ in range(120):  # the runner waits for its backend; be patient too
        if proc.poll() is not None:
            out = proc.stdout.read() if proc.stdout else ""
            pytest.fail(f"app.py exited early (rc={proc.returncode}):\n{out}")
        try:
            with urllib.request.urlopen(f"{base}/api/health", timeout=2) as r:
                if r.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.25)
    if not ready:
        proc.terminate()
        pytest.fail("app.py never became healthy on /api/health")
    yield {"base": base, "backend_port": bport}
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
        pytest.fail("app.py ignored SIGTERM — child processes would leak")


def test_shell_and_config(app):
    base = app["base"]
    status, headers, body = _get(base + "/")
    assert status == 200 and "ProcessPatch" in body.decode()
    assert headers.get("Content-Type", "").startswith("text/html")
    status, _, body = _get(base + "/config.js")
    assert status == 200
    assert b'window.PROCESSPATCH_API = "/api"' in body  # same-origin by design
    assert _get(base + "/../etc/passwd")[0] == 404        # traversal guard


def test_api_proxy_roundtrip(app):
    status, _, body = _get(app["base"] + "/api/demo/canonical?domain=research_grant")
    assert status == 200
    build = json.loads(body)
    assert build.get("build_id")
    assert isinstance(build.get("witnesses"), list) and build["witnesses"]


def test_seed_preloaded_demo_state(app):
    """make app must boot with content: a seeded build + at least one trace."""
    builds = _builds_list(app["base"])
    assert builds, "seed produced no builds — first-run UI would be empty"
    assert all(b.get("build_id") for b in builds)
    _, _, body = _get(app["base"] + "/api/traces")
    traces = json.loads(body)["traces"]
    assert traces, "seed produced no traces — Traces tab would be empty"


def test_seeded_build_has_trace_compare(app):
    bid = _builds_list(app["base"])[0]["build_id"]
    status, _, body = _get(f"{app['base']}/api/builds/{bid}/trace-compare")
    assert status == 200
    cmp = json.loads(body)
    assert isinstance(cmp.get("results"), list) and cmp["results"]


def test_csv_bulk_ingest_via_app(app):
    """Bulk CSV ingest: ingests, dedupes, fails closed — via the same proxy."""
    base = app["base"]
    csv = ("cgpa,amount,year,category,eligible,required\n"
           "7.2,0,3,general,approved,w-2\n"
           "6.4,0,2,obc,ineligible,\n")
    status, data = _post_json(base + "/api/traces/csv", {"csv": csv})
    assert status == 200, data
    assert data["ingested"] == 2
    # same batch again -> content-hashed dedupe, nothing new
    status, data2 = _post_json(base + "/api/traces/csv", {"csv": csv})
    assert status == 200 and data2["ingested"] == 0 and data2["duplicates"] == 2
    # one bad row -> whole batch rejected, nothing stored (fail-closed)
    bad = "cgpa,eligible\n7.0,approved\n9.9,not-a-bool\n"
    status, data3 = _post_json(base + "/api/traces/csv", {"csv": bad})
    assert status != 200 and "row 3" in json.dumps(data3)
    _, _, body = _get(base + "/api/traces")
    assert not any(t["case"].get("cgpa") == 9.9 for t in json.loads(body)["traces"])


def test_shutdown_reaps_backend_child(app, tmp_path):
    """After the runner exits, ITS backend port must refuse connections.

    Uses fresh ports (the module fixture is still alive here) — on Windows
    terminate() is TerminateProcess, so this exercises the Job Object path:
    the runner dies without running cleanup, and the job must kill the child.
    """
    port, bport = _free_port(), _free_port()
    proc = subprocess.Popen(
        [sys.executable, str(APP), "--no-open", "--port", str(port),
         "--backend-port", str(bport)],
        cwd=str(ROOT), env={**os.environ, "PROCESSPATCH_STORAGE": "files",
                            "PROCESSPATCH_DATA": str(tmp_path / "d2")},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    healthy = False
    for _ in range(120):
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                if r.status == 200:
                    healthy = True
                    break
        except Exception:
            if proc.poll() is not None:
                pytest.fail("second runner exited early")
            time.sleep(0.25)
    if not healthy:
        proc.kill()
        pytest.fail("second runner never became healthy")
    proc.terminate()
    proc.wait(timeout=15)
    time.sleep(0.5)
    with socket.socket() as s:
        s.settimeout(2)
        assert s.connect_ex(("127.0.0.1", bport)) != 0, \
            "backend child outlived the runner — orphaned process"
