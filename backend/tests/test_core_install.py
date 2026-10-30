"""`pip install elysian` without `[models]` must still remember, search and serve.

The models extra is gigabytes of torch; a module that imports it at load time would break the
plain install for everyone, so the core path is run in a fresh interpreter and its imports read.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

MODELS = ("torch", "torchvision", "transformers", "sentence_transformers", "peft", "datasets",
          "accelerate", "bitsandbytes", "qwen_vl_utils", "faster_whisper", "huggingface_hub", "safetensors")
CORE_RUN = f"""
import json, sys
from typer.testing import CliRunner
from elysian.api import create_app
from elysian.cli import app
create_app()
runner = CliRunner()
wrote = runner.invoke(app, ["remember", "the archive key is in the second drawer", "--holder", "wife"])
assert wrote.exit_code == 0, wrote.output
found = runner.invoke(app, ["search", "archive key", "--as-holder", "wife"])
assert found.exit_code == 0 and json.loads(found.output)["status"] == "hits", found.output
print(json.dumps(sorted(name for name in {MODELS!r} if name in sys.modules)))
"""


def test_remember_search_and_the_api_load_no_model_library(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", CORE_RUN],
        capture_output=True, text=True, cwd=tmp_path, env={"ELYSIAN_HOME": str(tmp_path / "home"), "PATH": ""},
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == []


def test_the_core_dependencies_hold_no_model_library() -> None:
    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    names = {requirement.split(">")[0].split("[")[0].split("=")[0].strip().replace("-", "_")
             for requirement in project["dependencies"]}

    assert names.isdisjoint(MODELS), names & set(MODELS)
    assert {"torch", "transformers"} <= {r.split(">")[0].replace("-", "_") for r in project["optional-dependencies"]["models"]}
