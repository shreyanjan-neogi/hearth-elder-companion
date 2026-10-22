import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Every test run uses its own throwaway database. Set before hearth is imported.
_TMP = tempfile.mkdtemp(prefix="hearth-test-")
os.environ["HEARTH_DB"] = os.path.join(_TMP, "unit.db")


@pytest.fixture()
def core():
    from hearth import core as c
    c.CLOCK.clear()
    c.seed_demo()
    yield c
    c.CLOCK.clear()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server():
    """Start the real server as a subprocess, the same way a user would."""
    port = _free_port()
    env = dict(os.environ, HEARTH_PORT=str(port), HEARTH_DB=os.path.join(_TMP, f"live-{port}.db"), HEARTH_HOST="127.0.0.1")
    proc = subprocess.Popen([sys.executable, "-m", "hearth.server"], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(base + "/api/health", timeout=1)
            break
        except Exception:
            time.sleep(0.25)
    else:
        proc.kill()
        raise RuntimeError("server did not start:\n" + proc.stdout.read().decode())
    yield base
    proc.terminate()
    proc.wait(timeout=5)
