"""Runtime observability shapes: what the model holds in memory right now."""

from typing import Literal

from pydantic import BaseModel

from .schemas import TrainingAdapterKind

AdapterState = Literal["loaded", "available", "deferred", "missing"]
AdapterOrigin = Literal["library", "cartridge"]


class AdapterChoice(BaseModel):
    """One adapter kind, and the honest reason it is or is not attached to the model."""

    kind: TrainingAdapterKind
    state: AdapterState
    reason: str
    path: str | None = None
    adapter_id: str | None = None
    base_model: str | None = None
    origin: AdapterOrigin | None = None
    cartridge_id: str | None = None
    shadowed: bool = False


class AdapterLoadReport(BaseModel):
    model_id: str
    mounted: list[str]
    adapters: list[AdapterChoice]
