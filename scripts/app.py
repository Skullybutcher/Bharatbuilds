"""ProcessPatch local app — ONE command, whole product.

    make app          (or: python scripts/app.py)

Serves the UI and the API on ONE port, so the demo is "open a URL":

  http://localhost:8080          -> the app (frontend/index.html + assets)
  http://localhost:8080/api/...  -> the full API (same actions as Lambda ApiFn)

Backend requests are forwarded to the existing stdlib server
(services/api/server.py) running on an internal port — the exact code that
backs production. Auth modes work here too:

  PROCESSPATCH_AUTH=off (default)              credential-free demo
  PROCESSPATCH_AUTH=hs256-test PP_DEV_HS256_SECRET=... PP_CLIENT_ID=demo ...
                                               enforced-auth demo

Stdlib only, no new dependencies.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".md": "text/plain; charset=utf-8",
}


class AppHandler(BaseHTTPRequestHandler):
    backend_port: int = 8001

    def log_message(self, *a):  # quiet
        pass

    # ------------------------------------------------------------- helpers --
    def _send(self, code: int, body: bytes, ctype: str, cache: bool = False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache" if not cache else "max-age=300")
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _proxy(self):
        """Forward /api/* to the backend (same actions as Lambda ApiFn)."""
        url = f"http://127.0.0.1:{self.backend_port}{self.path}"
        data = None
        if self.command == "POST":
            n = int(self.headers.get("Content-Length") or 0)
            data = self.rfile.read(n) if n else b"{}"
        req = urllib.request.Request(url, data=data, method=self.command)
        for h in ("Content-Type", "Authorization"):
            v = self.headers.get(h)
            if v:
                req.add_header(h, v)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                self._send(r.status, r.read(), r.headers.get("Content-Type", "application/json"))
        except urllib.error.HTTPError as e:
            self._send(e.code, e.read(), e.headers.get("Content-Type", "application/json"))
        except urllib.error.URLError as e:
            # One retry covers the brief window while the backend child is
            # still binding its port at startup; all our actions are
            # idempotent (content-hashed), so a replay is safe.
            time.sleep(0.3)
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    self._send(r.status, r.read(), r.headers.get("Content-Type", "application/json"))
                return
            except urllib.error.HTTPError as e2:
                self._send(e2.code, e2.read(), e2.headers.get("Content-Type", "application/json"))
            except Exception:
                body = f'{{"error": "backend unavailable: {e}"}}'.encode()
                self._send(502, body, "application/json")
        except Exception as e:  # backend down / timeout
            body = f'{{"error": "backend unavailable: {e}"}}'.encode()
            self._send(502, body, "application/json")

    # ------------------------------------------------------------- routing --
    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == "/api" or path.startswith("/api/"):
            self.path = "/" + self.path[len("/api/"):].lstrip("/") if len(self.path) > 4 else "/"
            return self._proxy()
        if path in ("/health", "/"):
            # App shell health: cheap liveness for the runner and smoke checks.
            if path == "/health":
                return self._send(200, b'{"app": "processpatch", "status": "ok"}',
                                  "application/json")
        if path == "/config.js":
            # Served by THIS app: point the UI at the same-origin /api proxy.
            # (Amplify generates its own config.js at build time; not used here.)
            body = b'window.PROCESSPATCH_API = "/api";\n'
            return self._send(200, body, MIME[".js"])
        file = FRONTEND / ("index.html" if path == "/" else path.lstrip("/"))
        file = file.resolve()
        if not str(file).startswith(str(FRONTEND.resolve())) or not file.is_file():
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        return self._send(200, file.read_bytes(),
                          MIME.get(file.suffix, "application/octet-stream"), cache=True)

    def do_POST(self):
        if self.path == "/api" or self.path.startswith("/api/"):
            self.path = "/" + self.path[len("/api/"):].lstrip("/") if len(self.path) > 4 else "/"
            return self._proxy()
        return self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_OPTIONS(self):  # same-origin app: minimal preflight support
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin",
                         os.environ.get("FRONTEND_ORIGIN", "*"))
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()


def _wait_backend(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.2)
    return False


def _job_object():
    """On Windows, tie the backend child's lifetime to ours: terminate() raises
    SIGTERM, which Windows does not deliver to Python signal handlers, so the
    child would otherwise outlive the runner (orphaned port). A Job Object with
    KILL_ON_JOB_CLOSE kills the whole tree when our last handle closes.
    Returns a ctypes handle, or None on non-Windows / on any failure (best-effort).
    """
    if sys.platform != "win32":
        return None
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # 64-bit HANDLEs: declare argtypes/restype explicitly or ctypes truncates.
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k32.CreateJobObjectW.restype = ctypes.c_void_p
    k32.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int,
                                            ctypes.c_void_p, ctypes.c_uint32]
    k32.SetInformationJobObject.restype = ctypes.c_bool
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = (ctypes.c_ulonglong * 18)()  # JOBOBJECT_EXTENDED_LIMIT_INFORMATION (144 bytes, x64)
    info[2] = 0x00002000  # LimitFlags (bytes 16..24) = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k32.SetInformationJobObject(job, 9, info,
                                       ctypes.sizeof(info)):  # JobObjectExtendedLimitInformation
        k32.CloseHandle(job)
        return None
    return job


def _assign_to_job(job, proc) -> bool:
    if not job or sys.platform != "win32":
        return False
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k32.AssignProcessToJobObject.restype = ctypes.c_bool
    return bool(k32.AssignProcessToJobObject(job, int(proc._handle)))


def _seed(backend_port: int) -> str:
    """Pre-load the canonical demo build + one runtime trace through the real
    API paths, so the UI has content on first open (and idempotent: content-
    derived ids mean re-seeding is a no-op)."""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{backend_port}/demo/canonical?domain=research_grant",
                timeout=60) as r:
            build = json.loads(r.read().decode())
        body = json.dumps({
            "case": {"cgpa": 7.8, "amount": 0, "year": 3, "backlogs": 0,
                     "category": "general", "submission_date": "2026-09-28"},
            "outcome": {"eligible": True}, "source": "runtime-log",
            "workflow_id": (build.get("procedure") or {}).get("workflow_id")}).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{backend_port}/traces", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            trace = json.loads(r.read().decode())
        return f"build {build.get('build_id')} ({len(build.get('witnesses', []))} witnesses) + trace {trace.get('trace_id')}"
    except Exception as e:  # noqa: BLE001 — seed is best-effort, never blocks the app
        return f"skipped ({e})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("APP_PORT", "8080")))
    ap.add_argument("--backend-port", type=int, default=int(os.environ.get("BACKEND_PORT", "8001")))
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--no-seed", action="store_true", help="skip pre-loading the demo build/trace")
    args = ap.parse_args()

    def _raise_interrupt(signum, frame):
        raise KeyboardInterrupt  # route SIGTERM/SIGBREAK into the cleanup path

    for s in ("SIGTERM", "SIGBREAK"):
        if hasattr(signal, s):
            try:
                signal.signal(getattr(signal, s), _raise_interrupt)
            except (ValueError, OSError):
                pass

    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    # The app gets its own data dir: first boot is seeded, later boots keep
    # your demo state, and dev/test data/ stays untouched. Override freely.
    env.setdefault("PROCESSPATCH_DATA", str(ROOT / ".app_data"))

    def _port_free(p: int) -> bool:
        import socket as _s
        with _s.socket(_s.AF_INET, _s.SOCK_STREAM) as sk:  # default = strict bind
            sk.bind(("127.0.0.1", p))
            return True

    bp = args.backend_port
    for attempt in range(args.backend_port, args.backend_port + 21):
        try:
            _port_free(attempt)
            bp = attempt
            break
        except OSError:
            continue
    else:
        print(f"no free backend port in {args.backend_port}..{args.backend_port + 20}",
              file=sys.stderr)
        return 1
    job = _job_object()
    backend_log = open(ROOT / ".app_backend.log", "w")  # backend tracebacks land here
    backend = subprocess.Popen(
        [sys.executable, "-m", "services.api.server", str(bp)],
        cwd=str(ROOT), env=env, stdout=backend_log, stderr=backend_log)
    if not _assign_to_job(job, backend):  # child dies with us, even on hard kill
        job = None
    if not _wait_backend(bp):
        print("backend failed to start", file=sys.stderr)
        backend.terminate()
        return 1

    handler = type("BoundAppHandler", (AppHandler,), {"backend_port": bp})

    class _AppServer(ThreadingHTTPServer):
        # On Windows SO_REUSEADDR can silently bind over an occupied port
        # (requests then go to the other service — a "blackhole" server).
        # Strict bind there so a busy port actually fails and we fall through.
        allow_reuse_address = sys.platform != "win32"

    frontend = None
    port = args.port
    for attempt in range(args.port, args.port + 11):
        try:
            frontend = _AppServer(("0.0.0.0", attempt), handler)
            port = attempt
            break
        except OSError:
            if attempt == args.port:
                print(f"port {attempt} is busy (another service owns it?) — trying {attempt + 1}…")
    if frontend is None:
        print(f"no free port found in {args.port}..{args.port + 10}; "
              "run with --port <free-port>", file=sys.stderr)
        backend.terminate()
        return 1
    threading.Thread(target=frontend.serve_forever, daemon=True).start()

    url = f"http://localhost:{port}"
    print("=" * 56)
    print(" ProcessPatch app")
    print(f"   UI     {url}" + ("" if port == args.port else f"  (default {args.port} was busy)"))
    print(f"   API    {url}/api  (same actions as the Lambda surface)")
    print(f"   auth   {os.environ.get('PROCESSPATCH_AUTH', 'off')}"
          "  (off = credential-free demo; see docs/auth.md)")
    print("   stop   Ctrl+C")
    print("=" * 56)

    if not args.no_seed:
        print(f"seeding demo… {_seed(args.backend_port)}")

    if not args.no_open:
        import webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        frontend.shutdown()
        backend.terminate()
        print("app stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
