"""Train the adapters: the service is a façade over the dataset, LoRA and retrieval modules."""

from __future__ import annotations

from pathlib import Path

from .config import Settings, get_settings
from .db import Database
from .schemas import AdapterManifest, TrainingAdapterKind
from .training_common import TrainingSample
from .training_datasets import (
    build_prd_dataset,
    build_retrieval_dataset,
    build_router_dataset,
    build_visual_dataset,
    validate_dataset,
)
from .training_lora import train_lora
from .training_retrieval import train_retrieval_lora


class TrainingService:
    def __init__(self, settings: Settings | None = None, database: Database | None = None) -> None:
        self.settings = settings or get_settings()
        self.db = database or Database(self.settings)

    def validate_dataset(self, path: Path) -> list[TrainingSample]:
        return validate_dataset(path)

    def build_prd_dataset(
        self,
        prd_path: Path,
        output_path: Path | None = None,
        cartridge_id: str | None = None,
        max_sections: int = 48,
    ) -> Path:
        return build_prd_dataset(self.settings, self.db, prd_path, output_path, cartridge_id, max_sections)

    def build_visual_dataset(
        self,
        prd_path: Path,
        output_path: Path | None = None,
        image_paths: list[Path] | None = None,
        cartridge_id: str | None = None,
    ) -> Path:
        return build_visual_dataset(self.settings, self.db, prd_path, output_path, image_paths, cartridge_id)

    def build_router_dataset(
        self,
        prd_path: Path,
        output_path: Path | None = None,
        cartridge_id: str | None = None,
    ) -> Path:
        return build_router_dataset(self.settings, self.db, prd_path, output_path, cartridge_id)

    def build_retrieval_dataset(
        self,
        prd_path: Path,
        output_path: Path | None = None,
        cartridge_id: str | None = None,
        max_sections: int = 32,
    ) -> Path:
        return build_retrieval_dataset(self.settings, self.db, prd_path, output_path, cartridge_id, max_sections)

    def train_lora(
        self,
        dataset_path: Path,
        output_dir: Path,
        max_steps: int,
        kind: TrainingAdapterKind = TrainingAdapterKind.hme_core_lora,
        model_id: str | None = None,
        rank: int = 16,
        alpha: int = 32,
        max_length: int | None = None,
        gradient_accumulation_steps: int | None = None,
        learning_rate: float | None = None,
        cartridge_id: str | None = None,
    ) -> AdapterManifest:
        return train_lora(self.settings, self.db, dataset_path, output_dir, max_steps, kind, model_id, rank, alpha, max_length, gradient_accumulation_steps, learning_rate, cartridge_id)

    def train_retrieval_lora(
        self,
        dataset_path: Path,
        output_dir: Path,
        max_steps: int,
        rank: int = 8,
        alpha: int = 16,
        max_length: int | None = None,
        learning_rate: float | None = None,
        cartridge_id: str | None = None,
    ) -> AdapterManifest:
        return train_retrieval_lora(self.settings, self.db, dataset_path, output_dir, max_steps, rank, alpha, max_length, learning_rate, cartridge_id)


