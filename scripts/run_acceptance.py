from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
LOG_DIR = ROOT / ".codex-logs" / "acceptance"


def _npm_cmd() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def _node_cmd() -> str:
    return "node.exe" if os.name == "nt" else "node"


def _wait_for_port(host: str, port: int, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for {host}:{port}: {last_error}")


def _run_step(name: str, command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print(f"\n== {name} ==")
    print(" ".join(command))
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"{name} failed with exit code {completed.returncode}")


def _start_process(name: str, command: list[str], *, cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stdout_path = LOG_DIR / f"{name}.out.log"
    stderr_path = LOG_DIR / f"{name}.err.log"
    stdout = stdout_path.open("a", encoding="utf-8")
    stderr = stderr_path.open("a", encoding="utf-8")
    print(f"Starting {name}; logs: {stdout_path}, {stderr_path}")
    return subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=stdout,
        stderr=stderr,
        text=True,
    )


def _stop_process(process: subprocess.Popen | None, name: str) -> None:
    if not process or process.poll() is not None:
        return
    print(f"Stopping {name}")
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run APS local acceptance checks.")
    parser.add_argument("--api-host", default="127.0.0.1")
    parser.add_argument("--api-port", default=8000, type=int)
    parser.add_argument("--web-host", default="127.0.0.1")
    parser.add_argument("--web-port", default=3000, type=int)
    parser.add_argument("--no-services", action="store_true", help="Use already-running API and web services.")
    parser.add_argument("--skip-e2e", action="store_true", help="Skip Playwright browser tests.")
    args = parser.parse_args(argv)

    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["APS_API_BASE_URL"] = f"http://{args.api_host}:{args.api_port}"
    env["APS_WEB_BASE_URL"] = f"http://{args.web_host}:{args.web_port}"

    api_process: subprocess.Popen | None = None
    web_process: subprocess.Popen | None = None

    try:
        _run_step("documentation status", [sys.executable, "scripts/validate_doc_status.py"], env=env)
        _run_step("backend unit tests", [sys.executable, "-m", "pytest", "tests", "-q"], env=env)
        _run_step(
            "frontend view-model tests",
            [
                _node_cmd(),
                "--test",
                "src/api/client.test.js",
                "src/pages/configPolicyViewModel.test.js",
                "src/pages/dashboardViewModel.test.js",
                "src/pages/ordersViewModel.test.js",
                "src/pages/workbenchViewModel.test.js",
            ],
            cwd=WEB,
            env=env,
        )
        _run_step("frontend lint", [_npm_cmd(), "run", "lint"], cwd=WEB, env=env)
        _run_step("frontend build", [_npm_cmd(), "run", "build"], cwd=WEB, env=env)

        if not args.no_services:
            api_process = _start_process(
                "uvicorn-8000",
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "api.main:app",
                    "--host",
                    args.api_host,
                    "--port",
                    str(args.api_port),
                ],
                cwd=ROOT,
                env=env,
            )
            web_process = _start_process(
                "vite-3000",
                [_npm_cmd(), "run", "dev", "--", "--host", args.web_host, "--port", str(args.web_port)],
                cwd=WEB,
                env=env,
            )

        _wait_for_port(args.api_host, args.api_port, 60)
        _wait_for_port(args.web_host, args.web_port, 60)

        http_env = {**env, "APS_RUN_HTTP_TESTS": "1"}
        _run_step(
            "HTTP API contract tests",
            [sys.executable, "-m", "pytest", "tests/test_api.py", "tests/test_preplan_contract.py", "-q"],
            env=http_env,
        )

        if not args.skip_e2e:
            _run_step(
                "Playwright smoke",
                [
                    _npm_cmd(),
                    "run",
                    "e2e",
                    "--",
                    "login.spec.js",
                    "smoke-routes.spec.js",
                    "localization.spec.js",
                    "config-policy.spec.js",
                ],
                cwd=WEB,
                env=env,
            )
            _run_step("Playwright workbench", [_npm_cmd(), "run", "e2e", "--", "workbench.spec.js"], cwd=WEB, env=env)
    finally:
        _stop_process(web_process, "Vite")
        _stop_process(api_process, "FastAPI")

    print("\nAcceptance checks completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
