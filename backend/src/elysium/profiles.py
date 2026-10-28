from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .config import Settings
from .runtime_schemas import RuntimeLaunchProfile, RuntimeProfileReport, RuntimeProfileValidation

EXTREME_YARN_OVERRIDE = {
    "text_config": {
        "rope_parameters": {
            "mrope_interleaved": True,
            "mrope_section": [11, 11, 10],
            "rope_type": "yarn",
            "rope_theta": 10_000_000,
            "partial_rotary_factor": 0.25,
            "factor": 4.0,
            "original_max_position_embeddings": 262_144,
        }
    }
}


def runtime_profile_report(settings: Settings, project_root: Path | None = None) -> RuntimeProfileReport:
    root = project_root or Path.cwd()
    profiles = [
        RuntimeLaunchProfile(
            name="sglang-live",
            runtime="SGLang",
            role="Main VLM service with MTP speculative decoding and Qwen tool/parser support.",
            context_tokens=262_144,
            script="scripts/launch-sglang-live.ps1",
            command=[
                "python",
                "-m",
                "sglang.launch_server",
                "--model-path",
                "Qwen/Qwen3.5-9B",
                "--port",
                "8000",
                "--tp-size",
                "1",
                "--mem-fraction-static",
                "0.82",
                "--context-length",
                "262144",
                "--reasoning-parser",
                "qwen3",
                "--speculative-algo",
                "NEXTN",
                "--speculative-num-steps",
                "3",
                "--speculative-num-draft-tokens",
                "4",
            ],
            required_features=["VLM", "MTP", "long-context", "tool-parser"],
        ),
        RuntimeLaunchProfile(
            name="sglang-extreme-yarn",
            runtime="SGLang",
            role="1.01M YaRN extreme-context service.",
            context_tokens=1_010_000,
            script="scripts/launch-sglang-extreme.ps1",
            command=[
                "python",
                "-m",
                "sglang.launch_server",
                "--model-path",
                "Qwen/Qwen3.5-9B",
                "--port",
                "8000",
                "--tp-size",
                "1",
                "--mem-fraction-static",
                "0.88",
                "--context-length",
                "1010000",
                "--json-model-override-args",
                "EXTREME_YARN_OVERRIDE",
            ],
            environment={"SGLANG_ALLOW_OVERWRITE_LONGER_CONTEXT_LEN": "1"},
            required_features=["YaRN", "long-context", "CPU-offload-compatible"],
        ),
        RuntimeLaunchProfile(
            name="vllm-live",
            runtime="vLLM",
            role="PagedAttention and Automatic Prefix Caching service for live document QA.",
            context_tokens=262_144,
            script="scripts/launch-vllm-live.ps1",
            command=[
                "python",
                "-m",
                "vllm.entrypoints.openai.api_server",
                "--model",
                "Qwen/Qwen3.5-9B",
                "--host",
                "127.0.0.1",
                "--port",
                "8001",
                "--max-model-len",
                "262144",
                "--enable-prefix-caching",
                "--gpu-memory-utilization",
                "0.82",
                "--trust-remote-code",
            ],
            required_features=["PagedAttention", "Automatic Prefix Caching", "OpenAI API"],
        ),
        RuntimeLaunchProfile(
            name="vllm-extreme-yarn",
            runtime="vLLM",
            role="1.01M YaRN profile with prefix cache and quantized KV-compatible launch args.",
            context_tokens=1_010_000,
            script="scripts/launch-vllm-extreme.ps1",
            command=[
                "python",
                "-m",
                "vllm.entrypoints.openai.api_server",
                "--model",
                "Qwen/Qwen3.5-9B",
                "--host",
                "127.0.0.1",
                "--port",
                "8001",
                "--max-model-len",
                "1010000",
                "--enable-prefix-caching",
                "--gpu-memory-utilization",
                "0.88",
                "--trust-remote-code",
                "--rope-scaling",
                "EXTREME_YARN_OVERRIDE",
            ],
            required_features=["YaRN", "PagedAttention", "Automatic Prefix Caching"],
        ),
        RuntimeLaunchProfile(
            name="ktransformers-extreme",
            runtime="KTransformers",
            role="SGLang-KT CPU-GPU heterogeneous ultra-long-context experiment service.",
            context_tokens=1_010_000,
            script="scripts/launch-ktransformers-extreme.ps1",
            command=[
                "python",
                "-m",
                "sglang.launch_server",
                "--model-path",
                "Qwen/Qwen3.5-9B",
                "--port",
                "8002",
                "--context-length",
                "1010000",
                "--kt-cpuinfer",
                "16",
                "--cpu-offload-gb",
                "48",
            ],
            required_features=["CPU-GPU heterogeneous execution", "ultra-long-context experiment"],
        ),
        RuntimeLaunchProfile(
            name="llamacpp-offline",
            runtime="llama.cpp",
            role="GGUF offline and portable local demo service.",
            context_tokens=262_144,
            script="scripts/launch-llamacpp-offline.ps1",
            command=[
                "llama-server",
                "--model",
                "$env:ELYSIUM_GGUF_MODEL",
                "--host",
                "127.0.0.1",
                "--port",
                "8003",
                "--ctx-size",
                "262144",
                "--flash-attn",
                "--cache-type-k",
                "q4_0",
                "--cache-type-v",
                "q4_0",
            ],
            environment={"ELYSIUM_GGUF_MODEL": "required absolute GGUF path"},
            required_features=["GGUF", "offline demo", "quantized KV"],
        ),
    ]
    validations = validate_runtime_profiles(root, profiles, settings)
    ready = all(validation.status == "ready" for validation in validations)
    return RuntimeProfileReport(
        status="ready" if ready else "incomplete",
        profiles=[profile.model_copy(update={"script": launch_script(profile.script)}) for profile in profiles],
        validations=validations,
    )


def uses_wsl() -> bool:
    """A Windows process reaches Linux through wsl.exe; inside WSL the local shell already is Linux."""
    if os.environ.get("WSL_DISTRO_NAME"):
        return False
    return shutil.which("wsl.exe") is not None


def launch_script(script: str) -> str:
    """A Windows host runs the .ps1; a Linux host, WSL included, runs the .sh twin."""
    return script if uses_wsl() else str(Path(script).with_suffix(".sh"))


def host_shell(command: str, settings: Settings) -> list[str]:
    """Run a shell command where the launch environments live."""
    if uses_wsl():
        return ["wsl.exe", "-d", settings.wsl_distro, "bash", "-lc", command]
    return ["bash", "-lc", command]


def host_path(root: Path) -> str:
    """The path the host shell can cd into; a Windows path is reached through the WSL mount."""
    resolved = root.resolve()
    return windows_path_to_wsl(resolved) if uses_wsl() else str(resolved)


def validate_runtime_profiles(
    root: Path,
    profiles: list[RuntimeLaunchProfile],
    settings: Settings,
) -> list[RuntimeProfileValidation]:
    gpu = gpu_available(settings)
    package_cache = {
        ".venv-linux": linux_package_versions(root, ".venv-linux", settings),
        ".venv-linux-vllm": linux_package_versions(root, ".venv-linux-vllm", settings),
    }
    probe_cache: dict[tuple[str, str, str | None], dict[str, object]] = {}
    llama_server = resolve_llama_server()
    validations: list[RuntimeProfileValidation] = []
    for profile in profiles:
        script_exists = (root / launch_script(profile.script)).exists()
        package = package_for_runtime(profile.runtime)
        env_name = linux_env_for_runtime(profile.runtime)
        linux_packages = package_cache.get(env_name, {})
        package_version = linux_packages.get(package) if package else None
        kt_sglang_version = linux_packages.get("sglang") if profile.runtime == "KTransformers" else None
        executable = llama_server if profile.runtime == "llama.cpp" else None
        probe_key = (profile.runtime, env_name, executable)
        if probe_key not in probe_cache:
            probe_cache[probe_key] = runtime_launcher_probe(root, profile.runtime, env_name, executable, settings)
        probe = probe_cache[probe_key]
        probe_status = str(probe.get("status", "skipped"))
        probe_passed = probe_status == "passed"
        if profile.runtime in {"SGLang", "vLLM", "KTransformers"}:
            ready = script_exists and bool(package_version) and gpu and probe_passed
            if profile.runtime == "KTransformers":
                ready = ready and bool(kt_sglang_version)
            detail = (
                (
                    f"GPU ready; {package} {package_version}; "
                    f"sglang-kt entry {kt_sglang_version}"
                )
                if profile.runtime == "KTransformers" and ready
                else f"GPU ready; {package} {package_version}; env {env_name}"
                if ready
                else (
                    f"script={script_exists}, gpu={gpu}, env={env_name}, "
                    f"{package}={package_version}, sglang={kt_sglang_version}"
                )
            )
        elif profile.runtime == "llama.cpp":
            ready = script_exists and bool(executable) and probe_passed
            detail = f"llama-server at {executable}" if ready else "llama-server executable missing"
        else:
            ready = script_exists
            detail = f"script={script_exists}"
        detail = f"{detail}; launcher_probe={probe_status}"
        validations.append(
            RuntimeProfileValidation(
                name=profile.name,
                runtime=profile.runtime,
                status="ready" if ready else "missing",
                script_exists=script_exists,
                package=package,
                package_version=package_version,
                executable=executable,
                gpu_available=gpu,
                probe_command=[str(item) for item in probe.get("command", [])],
                probe_status=probe_status,
                probe_exit_code=probe.get("exit_code") if isinstance(probe.get("exit_code"), int) else None,
                probe_output=probe.get("output") if isinstance(probe.get("output"), str) else None,
                detail=detail,
            )
        )
    return validations


def package_for_runtime(runtime: str) -> str | None:
    return {
        "SGLang": "sglang",
        "vLLM": "vllm",
        "KTransformers": "ktransformers",
    }.get(runtime)


def linux_env_for_runtime(runtime: str) -> str:
    if runtime == "vLLM":
        return ".venv-linux-vllm"
    return ".venv-linux"


def linux_package_versions(root: Path, env_name: str, settings: Settings) -> dict[str, str]:
    script = (
        "import importlib.metadata as md, json;"
        "names=['sglang','vllm','ktransformers','torch','torchvision','qwen-vl-utils'];"
        "out={};"
        "\nfor name in names:\n"
        "    try: out[name]=md.version(name)\n"
        "    except Exception: pass\n"
        "print(json.dumps(out))"
    )
    try:
        output = subprocess.check_output(
            host_shell(
                f"cd {wsl_quote(host_path(root))} "
                f"&& test -x {env_name}/bin/python "
                f"&& {env_name}/bin/python -c {wsl_quote(script)}",
                settings,
            ),
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
        payload = json.loads(output.strip())
        if not isinstance(payload, dict):
            return {}
        return {str(key): str(value) for key, value in payload.items()}
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}


def runtime_launcher_probe(
    root: Path,
    runtime: str,
    env_name: str,
    executable: str | None,
    settings: Settings,
) -> dict[str, object]:
    if runtime == "SGLang":
        probe_script = (
            "import importlib.util, sys; "
            "spec=importlib.util.find_spec('sglang.launch_server'); "
            "print(spec.origin if spec else 'missing'); "
            "sys.exit(0 if spec else 1)"
        )
        command = host_python_command(root, env_name, f"-c {wsl_quote(probe_script)}", settings)
    elif runtime == "vLLM":
        probe_script = (
            "import importlib.util, sys; "
            "spec=importlib.util.find_spec('vllm.entrypoints.openai.api_server'); "
            "print(spec.origin if spec else 'missing'); "
            "sys.exit(0 if spec else 1)"
        )
        command = host_python_command(root, env_name, f"-c {wsl_quote(probe_script)}", settings)
    elif runtime == "KTransformers":
        probe_script = "import ktransformers, sglang; print('ktransformers and sglang import ok')"
        command = host_python_command(root, env_name, f"-c {wsl_quote(probe_script)}", settings)
    elif runtime == "llama.cpp" and executable:
        command = [executable, "--help"]
    else:
        return {"status": "skipped", "command": [], "output": "no launcher probe configured"}
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "status": "failed",
            "command": command,
            "exit_code": None,
            "output": str(exc).splitlines()[0],
        }
    output = compact_output(completed.stdout, completed.stderr)
    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "command": command,
        "exit_code": completed.returncode,
        "output": output,
    }


def host_python_command(root: Path, env_name: str, python_args: str, settings: Settings) -> list[str]:
    shell_command = (
        f"cd {wsl_quote(host_path(root))} "
        f"&& test -x {env_name}/bin/python "
        f"&& {env_name}/bin/python {python_args}"
    )
    return host_shell(shell_command, settings)


def compact_output(stdout: str, stderr: str, limit: int = 800) -> str:
    text = "\n".join(part.strip() for part in (stdout, stderr) if part.strip())
    return text[:limit]


def gpu_available(settings: Settings) -> bool:
    """Ask the host for a CUDA-capable GPU without naming a card: any GPU the driver lists will do."""
    try:
        output = subprocess.check_output(
            host_shell("nvidia-smi -L", settings),
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
        return "GPU" in output
    except (OSError, subprocess.SubprocessError):
        return False


def resolve_llama_server() -> str | None:
    configured = os.environ.get("LLAMA_CPP_SERVER")
    if configured and Path(configured).exists():
        return configured
    direct = shutil.which("llama-server")
    if direct:
        return direct
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    package_root = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
    matches = sorted(package_root.glob("ggml.llamacpp_*/*llama-server.exe"))
    return str(matches[-1]) if matches else None


def windows_path_to_wsl(path: Path) -> str:
    """Map a Windows path to the WSL mount a WSL shell can cd into; a POSIX path is already correct."""
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        return str(resolved)
    return "/mnt/" + drive + "/" + "/".join(resolved.parts[1:])


def wsl_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
