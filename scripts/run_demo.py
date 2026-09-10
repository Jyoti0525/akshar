"""Bring up the whole thing on a laptop, with no Docker. AKSHAR.md section 20.

    python scripts/run_demo.py

Starts the API on :8000 against the in-memory stores and the web app on :3000
pointed at it. Ctrl-C stops both.

The instance is **empty** unless `--seed` is passed. An empty instance is what a
real deployment looks like on its first morning, and it is the only state in
which nothing on screen can be mistaken for a finding; `--seed` fills it from
`api/demo.py` when the dashboards need to have something in them.

**Why this exists rather than `docker compose up`.** Compose is the real answer
and `docker/` still holds it, but it wants Postgres, Redis, MinIO and a Docker
daemon, and the one thing that must not happen the morning of a demonstration is
discovering that Docker Desktop will not start. Everything in this system was
already built to run without a database — the stores are Protocols, the API
falls back to memory, `rules/` and `vision/` take their lookups from the caller —
so the no-Docker path is not a special mode written for this script. It is the
architecture, used.

**What is real and what is not**, because a demonstration that blurs this is
worse than none: the rules engine, the rulepack, the applicability gates, the
evidence chain, the API, the dashboard arithmetic and every verdict on screen
are the production code paths. The *packets* are invented — see `api/demo.py`.
Nothing here runs the vision pipeline, so no accuracy number may be quoted from
it; `RESULTS.md` is the only place those live.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

API_PORT = 8000
WEB_PORT = 3000


def _log(message: str) -> None:
    print(f"  {message}", flush=True)


def _wait_for(url: str, *, timeout: float, what: str) -> bool:
    """Poll until the thing answers, or give up and say so."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return True
        except (URLError, OSError):
            time.sleep(0.5)
    _log(f"! {what} did not answer at {url} within {timeout:.0f}s")
    return False


def _npm() -> str | None:
    # `npm` is `npm.cmd` on Windows and `shutil.which` is the only reliable way
    # to find it; hardcoding either name breaks on the other platform.
    return shutil.which("npm")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-only",
        action="store_true",
        help="Start only the API. Useful when the web app is already running.",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help=(
            "Run the web app with `next dev` instead of a production build. "
            "Faster to start; the service worker does not register, so the "
            "offline demonstration will not work."
        ),
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help=(
            "Fill the API with the synthetic shelf in api/demo.py — 16 SKUs, "
            "260 scans, 6 districts. Off by default: an empty instance is what "
            "a real deployment looks like on day one, and invented brand names "
            "on a dashboard are easy to mistake for findings. Every verdict it "
            "produces still comes from the real rulepack."
        ),
    )
    parser.add_argument(
        "--https",
        action="store_true",
        help=(
            "Serve the web app over https with a self-signed certificate, so "
            "the camera works when the app is opened from a phone on the same "
            "network. Browsers only expose getUserMedia in a secure context, "
            "and http://192.168.x.x is not one. Implies --dev: `next start` "
            "has no equivalent flag."
        ),
    )
    args = parser.parse_args()
    if args.https:
        args.dev = True

    # The Windows console is cp1252 unless told otherwise, and the banner below
    # is the one thing anyone reads. `errors="replace"` rather than a crash: a
    # mangled dash is a nuisance, a UnicodeEncodeError in a launcher is a
    # demonstration that does not start.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")

    env = os.environ.copy()
    env["AKSHAR_STORAGE"] = "memory"
    env["AKSHAR_DEMO_SEED"] = "1" if args.seed else "0"
    env["AKSHAR_ENVIRONMENT"] = "development"
    env["PYTHONUTF8"] = "1"

    processes: list[subprocess.Popen[bytes]] = []
    scheme = "https" if args.https else "http"

    print()
    print("AKSHAR — demonstration stack")
    print("=" * 60)

    _log(f"api   http://localhost:{API_PORT}   "
         f"(in-memory, {'seeded' if args.seed else 'empty'})")
    api = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(API_PORT),
            "--log-level",
            "warning",
        ],
        cwd=ROOT,
        env=env,
    )
    processes.append(api)

    if not _wait_for(f"http://localhost:{API_PORT}/healthz", timeout=60, what="API"):
        api.terminate()
        return 1
    _log(f"api   ready — docs at http://localhost:{API_PORT}/docs")

    if not args.api_only:
        npm = _npm()
        if npm is None:
            _log("! npm not found on PATH; starting the API alone")
        else:
            web_env = env.copy()
            # Server-side only. The browser never learns the API origin: it
            # calls same-origin /api/v1/* and the route handler adds the bearer
            # from the httpOnly cookie. See docs/deployment.md section 2.
            web_env["AKSHAR_API_ORIGIN"] = f"http://localhost:{API_PORT}"
            web_env["NODE_ENV"] = "development" if args.dev else "production"

            if not args.dev and not (WEB / ".next" / "BUILD_ID").exists():
                _log("web   building (first run only, ~40s) ...")
                built = subprocess.run([npm, "run", "build"], cwd=WEB, env=web_env)
                if built.returncode != 0:
                    _log("! web build failed; the API is still up")
                    npm = None

            if npm is not None:
                _log(f"web   {scheme}://localhost:{WEB_PORT}")
                script = "dev" if args.dev else "start"
                command = [npm, "run", script, "--", "--port", str(WEB_PORT)]
                if args.https:
                    # Next generates and trusts a local certificate the first
                    # time; on Windows that pops a one-off consent dialogue.
                    command.append("--experimental-https")
                processes.append(subprocess.Popen(command, cwd=WEB, env=web_env))
                _wait_for(f"{scheme}://localhost:{WEB_PORT}/login", timeout=120, what="web app")

    print("=" * 60)
    print("  Sign in with any of these — password: akshar-demo")
    print()
    print("    officer@akshar.demo      scan, queue, own scans")
    print("    supervisor@akshar.demo   + dashboard, review queue, exports")
    print("    admin@akshar.demo        + everything")
    print()
    if args.seed:
        print("  The packets are invented. The verdicts are not: every one comes")
        print("  from rules/packs/lmpc_2011.yaml. See api/demo.py.")
    else:
        print("  This instance is EMPTY — scan or upload a photograph to fill it.")
        print("  For a populated dashboard:  python scripts/run_demo.py --seed")
    if not args.https:
        print()
        print("  Camera from a phone on this network? Browsers only allow it over")
        print("  https, so use:  python scripts/run_demo.py --https")
    print("=" * 60)
    print("  Ctrl-C to stop.", flush=True)

    try:
        while True:
            for process in processes:
                if process.poll() is not None:
                    _log(f"! a process exited with {process.returncode}; shutting down")
                    raise KeyboardInterrupt
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n  stopping ...", flush=True)
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                # Terminate, then wait, then insist. A `next start` that is only
                # SIGINTed keeps port 3000 and the next run fails confusingly.
                process.send_signal(signal.SIGTERM)
        for process in reversed(processes):
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
