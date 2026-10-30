from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The project was called Ely-Eye; a name it no longer reads must stop the process, not be ignored.
OLD_ENV_PREFIX = "ELY_EYE_"
OLD_HOME_NAME = ".ely_eye"
OLD_DATABASE_NAME = "ely_eye.sqlite"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ELYSIUM_", env_file=".env", extra="ignore")

    home: Path = Field(default_factory=lambda: Path.cwd() / ".elysium")
    default_holder: str = "local"
    auth_token: str | None = None
    allowed_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    model_id: str = "Qwen/Qwen3.5-9B"
    model_dir: Path | None = None
    kv_cache_dtype: str = "auto"
    planner_model_id: str = "Qwen/Qwen3.5-0.8B"
    embedding_model_id: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_model_dir: Path | None = None
    clip_model_dir: Path | None = None
    vlm_base_url: str | None = None
    vlm_max_new_tokens: int = 512
    rerank_base_url: str | None = None
    asr_model_dir: Path | None = None
    adapter_dir: Path | None = None
    runtime_backend: Literal["sglang", "transformers"] = "transformers"
    sglang_base_url: str = "http://127.0.0.1:8000/v1"
    sglang_api_key: str = "elysium-local"
    ui_dir: Path | None = None
    wsl_distro: str = "Ubuntu"
    dense_embeddings_enabled: bool = False
    live_context_tokens: int = 262_144
    extreme_context_tokens: int = 1_010_000
    library_target_tokens: int = 100_000_000
    upload_max_bytes: int = 20 * 1024 * 1024 * 1024
    video_sample_seconds: float = 5.0
    max_text_file_bytes: int = 10 * 1024 * 1024
    retrieval_top_k: int = 24
    max_new_tokens: int = 512
    temperature: float = 0.1
    train_max_length: int = 8192
    train_gradient_accumulation_steps: int = 8
    train_learning_rate: float = 2e-4

    @property
    def data_dir(self) -> Path:
        return self.home / "data"

    @property
    def object_dir(self) -> Path:
        return self.home / "objects"

    @property
    def cartridge_dir(self) -> Path:
        return self.home / "cartridges"

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    @property
    def training_dir(self) -> Path:
        return self.home / "training"

    @property
    def adapters_dir(self) -> Path:
        return self.home / "adapters"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "elysium.sqlite"

    @model_validator(mode="after")
    def _refuse_old_names(self) -> Settings:
        refuse_old_names(self, dict(os.environ), Path.cwd())
        return self

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.object_dir,
            self.cartridge_dir,
            self.cache_dir,
            self.training_dir,
            self.adapters_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def refuse_old_names(settings: Settings, environment: dict[str, str], cwd: Path) -> None:
    """Fail on any trace of the old name instead of starting a second, empty store beside it.

    Ignoring ELY_EYE_AUTH_TOKEN would start a server with no token at all, and an old home or
    database left where the new one is looked for would be silently replaced by a fresh one.
    """
    dotenv = cwd / ".env"
    names = list(environment) + (list(dotenv_values(dotenv)) if dotenv.is_file() else [])
    old = sorted(name for name in names if name.startswith(OLD_ENV_PREFIX))
    if "ELYSIUM_VLM_MODEL_DIR" in names:
        raise SystemExit(
            "ELYSIUM_VLM_MODEL_DIR is set, but pictures are now described by a served model: "
            "set ELYSIUM_VLM_BASE_URL to its /v1 URL (scripts/launch-vllm-live.sh serves one)"
        )
    if old:
        raise SystemExit(
            f"{old[0]} is set, but this project is now Elysium and reads ELYSIUM_{old[0][len(OLD_ENV_PREFIX):]}; "
            "rename every ELY_EYE_* variable (under the old name it would be ignored)"
        )
    home = (cwd / settings.home).resolve()
    legacy_home = home.parent / OLD_HOME_NAME
    if home.name == ".elysium" and legacy_home.is_dir() and not home.exists():
        raise SystemExit(f"{legacy_home} is the data home from before the rename; move it to {home}")
    database = home / settings.db_path.relative_to(settings.home)
    legacy_database = database.with_name(OLD_DATABASE_NAME)
    if legacy_database.is_file() and not database.exists():
        raise SystemExit(
            f"{legacy_database} is a store from before the rename; move it to {database} "
            "(the bytes are unchanged) rather than letting a second, empty store start beside it"
        )

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
