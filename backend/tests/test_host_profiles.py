"""The launch layer must describe the machine it runs on, not the one it was written on."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from ely_eye import profiles
from ely_eye.config import Settings
from ely_eye.proofs.training_trace import cuda_bf16_training
from ely_eye.training_metrics import require_cuda_bf16


def _stub_nvidia_smi(tmp_path: Path, monkeypatch, output: str, exit_code: int = 0) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "nvidia-smi"
    stub.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\nexit {exit_code}\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_a_gpu_that_is_not_the_written_down_card_still_counts(tmp_path: Path, monkeypatch) -> None:
    _stub_nvidia_smi(tmp_path, monkeypatch, "GPU 0: NVIDIA GeForce RTX 5090 (UUID: GPU-1234)")
    monkeypatch.setattr(profiles, "uses_wsl", lambda: False)
    assert profiles.gpu_available(Settings(home=tmp_path / "home")) is True


def test_a_machine_the_driver_cannot_see_reports_no_gpu(tmp_path: Path, monkeypatch) -> None:
    _stub_nvidia_smi(tmp_path, monkeypatch, "nvidia-smi: command not found", exit_code=127)
    monkeypatch.setattr(profiles, "uses_wsl", lambda: False)
    assert profiles.gpu_available(Settings(home=tmp_path / "home")) is False


def test_the_distro_name_comes_from_settings(monkeypatch) -> None:
    monkeypatch.setattr(profiles, "uses_wsl", lambda: True)
    command = profiles.host_shell("true", Settings(home=Path("/tmp"), wsl_distro="Ubuntu-24.04"))
    assert command == ["wsl.exe", "-d", "Ubuntu-24.04", "bash", "-lc", "true"]


def test_inside_wsl_the_local_shell_runs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    monkeypatch.setattr(profiles.shutil, "which", lambda name: "/mnt/c/WINDOWS/system32/wsl.exe")
    assert profiles.uses_wsl() is False
    monkeypatch.delenv("WSL_DISTRO_NAME")
    assert profiles.uses_wsl() is True
    assert profiles.host_shell("true", Settings(home=tmp_path / "home", wsl_distro="Ubuntu"))[0] == "wsl.exe"


def test_a_linux_host_is_pointed_at_the_shell_twin(monkeypatch) -> None:
    monkeypatch.setattr(profiles, "uses_wsl", lambda: False)
    assert profiles.launch_script("scripts/launch-sglang-live.ps1") == "scripts/launch-sglang-live.sh"
    monkeypatch.setattr(profiles, "uses_wsl", lambda: True)
    assert profiles.launch_script("scripts/launch-sglang-live.ps1") == "scripts/launch-sglang-live.ps1"


def test_the_training_verdict_does_not_name_a_card() -> None:
    newer = {"cuda_available": True, "bf16_supported": True, "device_name": "NVIDIA GeForce RTX 5090"}
    assert cuda_bf16_training(newer) is True
    older = {"cuda_available": True, "bf16_supported": True, "device_name": "NVIDIA GeForce RTX 4080"}
    assert cuda_bf16_training(older) is True
    without_bf16 = {"cuda_available": True, "bf16_supported": False, "device_name": "NVIDIA GeForce RTX 4090"}
    assert cuda_bf16_training(without_bf16) is False


class _FakeCuda:
    def __init__(self, available: bool, bf16: bool) -> None:
        self._available = available
        self._bf16 = bf16

    def is_available(self) -> bool:
        return self._available

    def is_bf16_supported(self) -> bool:
        return self._bf16


class _FakeTorch:
    def __init__(self, available: bool, bf16: bool) -> None:
        self.cuda = _FakeCuda(available, bf16)


def test_training_refuses_a_machine_without_cuda_by_capability_not_card() -> None:
    with pytest.raises(RuntimeError) as refused:
        require_cuda_bf16(_FakeTorch(available=False, bf16=False))
    assert "4090" not in str(refused.value)
    require_cuda_bf16(_FakeTorch(available=True, bf16=True))


def test_every_profile_ships_a_script_for_this_host(tmp_path: Path, monkeypatch) -> None:
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(profiles, "uses_wsl", lambda: False)
    linux = profiles.runtime_profile_report(Settings(home=tmp_path / "home"), root)
    assert [item.name for item in linux.validations if not item.script_exists] == []
    assert all(item.script.endswith(".sh") for item in linux.profiles), linux.profiles
    monkeypatch.setattr(profiles, "uses_wsl", lambda: True)
    windows = profiles.runtime_profile_report(Settings(home=tmp_path / "home"), root)
    assert [item.name for item in windows.validations if not item.script_exists] == []
    assert all(item.script.endswith(".ps1") for item in windows.profiles), windows.profiles
