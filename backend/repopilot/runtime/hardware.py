"""Describe the machine so RepoPilot only picks models that fit in memory."""

from __future__ import annotations

import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass

import psutil


@dataclass(frozen=True)
class Hardware:
    total_ram_bytes: int
    gpu: str | None
    vram_bytes: int | None
    unified_memory: bool

    @property
    def model_budget_bytes(self) -> int:
        """Memory a model may occupy: 80% of VRAM (or unified/system RAM)."""
        return int(0.8 * (self.vram_bytes or self.total_ram_bytes))

    def to_dict(self) -> dict:
        return {**asdict(self), "model_budget_bytes": self.model_budget_bytes}


def _nvidia() -> tuple[str, int] | None:
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    if not out:
        return None
    name, mib = out.splitlines()[0].rsplit(",", 1)
    return name.strip(), int(float(mib.strip())) * 1024 * 1024


def hardware() -> Hardware:
    ram = psutil.virtual_memory().total
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        chip = "Apple Silicon"
        try:
            chip = (
                subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, timeout=2
                ).stdout.strip()
                or chip
            )
        except (subprocess.SubprocessError, OSError):
            pass
        return Hardware(ram, chip, int(ram * 0.75), True)
    nvidia = _nvidia()
    if nvidia:
        return Hardware(ram, nvidia[0], nvidia[1], False)
    return Hardware(ram, None, None, False)
