from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ProcResult:
    code: int
    out: str
    err: str

    @property
    def text(self) -> str:
        return (self.out + ("\n" + self.err if self.err else "")).strip()


def uv_bin() -> str:
    return shutil.which("uv") or "uv"


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> ProcResult:
    env = dict(os.environ)
    # A parent `uv run` exports VIRTUAL_ENV; uv would otherwise warn/ignore the
    # project environment we are explicitly inspecting.
    for key in ("VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONHOME"):
        env.pop(key, None)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return ProcResult(proc.returncode, proc.stdout or "", proc.stderr or "")
    except FileNotFoundError:
        return ProcResult(127, "", f"command not found: {cmd[0]}")
    except subprocess.TimeoutExpired:
        return ProcResult(124, "", f"timed out after {timeout}s: {' '.join(cmd)}")
    except Exception as exc:  # pragma: no cover
        return ProcResult(1, "", str(exc))
