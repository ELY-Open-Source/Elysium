"""The product face: page the store, look at a picture, and say plainly what the machine can perceive."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import elysium.api as api_module
from elysium.config import Settings
from elysium.db import Database
from elysium.memory import MemoryService
from elysium.schemas import EvidenceAtom, MemoryOrigin, Modality, SourceRecord, TrustScores
from elysium.storage import ObjectStore

PNG = b"\x89PNG\r\n\x1a\n"
BASE = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
OPERATOR = "the-shelf-owner"
AS_OWNER = {"Authorization": f"Bearer {OPERATOR}"}

HTTP_SURFACE = {
    "/api/adapters",
    "/api/ask",
    "/api/atoms",
    "/api/atoms/{atom_id}/image",
    "/api/cartridges",
    "/api/cartridges/{cartridge_id}/append",
    "/api/cartridges/{cartridge_id}/assets",
    "/api/cartridges/{cartridge_id}/finalize",
    "/api/cartridges/{cartridge_id}/mount",
    "/api/cartridges/{cartridge_id}/refresh",
    "/api/cartridges/{cartridge_id}/switch",
    "/api/cartridges/{cartridge_id}/unmount",
    "/api/card",
    "/api/card/{holder_id}",
    "/api/chat",
    "/api/hashhop",
    "/api/holders",
    "/api/holders/{holder_id}",
    "/api/holders/{holder_id}/knows",
    "/api/holders/{holder_id}/token",
    "/api/ingest/path",
    "/api/ingest/upload",
    "/api/memory",
    "/api/memory/conflicts",
    "/api/memory/forget",
    "/api/memory/supersede",
    "/api/memory/working",
    "/api/mounts",
    "/api/proof-suite",
    "/api/proof-suite/latest",
    "/api/runtime/adapters",
    "/api/runtime/profiles",
    "/api/search",
    "/api/status",
    "/api/who_knows",
}


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    resolved = Settings(home=tmp_path, default_holder="wife", auth_token=OPERATOR)
    monkeypatch.setattr(api_module, "get_settings", lambda: resolved)
    Database(resolved).init()
    return resolved


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(api_module.create_app())


def _seed(settings: Settings, pictures: int = 3) -> None:
    """Pictures an hour apart, so newest-first has a fact to order by rather than a coincidence."""
    database = Database(settings)
    trust = TrustScores(parser=1.0, ocr=0.0, model=0.0)
    store = ObjectStore(settings)
    stored = store.put_bytes(PNG, ".png", "image")
    database.upsert_sources(
        [
            SourceRecord(
                source_id=f"shot{i}",
                path=f"file:///shot{i}.png",
                kind="image",
                mime="image/png",
                sha256=f"{i}" * 8,
                size_bytes=len(PNG),
            )
            for i in range(pictures)
        ]
    )
    database.upsert_atoms(
        [
            EvidenceAtom(
                atom_id=f"shot{i}:frame",
                modality=Modality.image,
                source_id=f"shot{i}",
                source=f"file:///shot{i}.png",
                trust=trust,
                image_ref=stored,
                holder_id="wife" if i % 2 == 0 else "husband",
                ingested_at=BASE + timedelta(hours=i),
            )
            for i in range(pictures)
        ]
    )


def test_the_store_pages_newest_first_and_says_how_much_is_left(client: TestClient, settings: Settings) -> None:
    _seed(settings)
    # A tokenless caller is nobody and would see none of these; this test reads the shelf as its owner.
    first = client.get("/api/atoms", params={"limit": 2}, headers=AS_OWNER)
    assert first.status_code == 200
    page = first.json()
    assert page["total"] == 3
    assert [atom["atom_id"] for atom in page["atoms"]] == ["shot2:frame", "shot1:frame"]
    assert page["next_cursor"]

    second = client.get("/api/atoms", params={"limit": 2, "cursor": page["next_cursor"]}, headers=AS_OWNER)
    rest = second.json()
    assert [atom["atom_id"] for atom in rest["atoms"]] == ["shot0:frame"]
    assert rest["next_cursor"] is None, "the last page must not promise another one"


def test_browse_narrows_by_modality_and_by_holder(client: TestClient, settings: Settings) -> None:
    _seed(settings, pictures=2)
    MemoryService(settings, Database(settings)).remember(
        "the keys are on the shelf", holder_id="wife", origin=MemoryOrigin.self_
    )

    images = client.get("/api/atoms", params={"modality": "image"}, headers=AS_OWNER).json()
    assert images["total"] == 2
    assert {atom["modality"] for atom in images["atoms"]} == {"image"}

    his = client.get("/api/atoms", params={"holder": "husband"}, headers=AS_OWNER).json()
    assert [atom["atom_id"] for atom in his["atoms"]] == ["shot1:frame"]


def test_an_unreadable_cursor_is_refused_with_400(client: TestClient, settings: Settings) -> None:
    _seed(settings, pictures=1)
    response = client.get("/api/atoms", params={"cursor": "not-a-cursor"})
    assert response.status_code == 400
    assert "cursor" in response.json()["detail"]


def test_a_picture_atom_serves_the_bytes_behind_it(client: TestClient, settings: Settings) -> None:
    _seed(settings, pictures=1)
    response = client.get("/api/atoms/shot0:frame/image", headers=AS_OWNER)
    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-type"] == "image/png"


def test_a_memory_with_no_picture_says_so(client: TestClient, settings: Settings) -> None:
    atom = MemoryService(settings, Database(settings)).remember(
        "the keys are on the shelf", holder_id="wife", origin=MemoryOrigin.self_
    )
    assert client.get(f"/api/atoms/{atom.atom_id}/image", headers=AS_OWNER).status_code == 404
    assert client.get("/api/atoms/nope:image", headers=AS_OWNER).status_code == 404


def test_a_forgotten_picture_stops_being_served(client: TestClient, settings: Settings) -> None:
    _seed(settings, pictures=1)
    MemoryService(settings, Database(settings)).forget(atom_id="shot0:frame")
    assert client.get("/api/atoms/shot0:frame/image", headers=AS_OWNER).status_code == 404
    assert client.get("/api/atoms", headers=AS_OWNER).json()["total"] == 0


def test_status_says_what_the_machine_can_see_and_what_it_cannot(client: TestClient, settings: Settings) -> None:
    _seed(settings, pictures=2)
    senses = client.get("/api/status").json()["senses"]
    assert senses["dense"] == "off", "dense embeddings are off by default and status must not claim otherwise"
    assert senses["picture_atoms"] == 2
    assert senses["picture_bytes_missing"] == 0
    assert senses["visual"] == "absent", "no CLIP snapshot on this machine means wordless pictures stay hidden"
    assert senses["speech"] == "absent"


def test_status_names_pictures_whose_bytes_are_gone(client: TestClient, settings: Settings) -> None:
    _seed(settings, pictures=1)
    dead = Database(settings).get_atoms(["shot0:frame"])[0].model_copy(
        update={"atom_id": "shot0:ghost", "image_ref": "object://image/ab/deadbeef.png"}
    )
    Database(settings).upsert_atoms([dead])
    senses = client.get("/api/status").json()["senses"]
    assert senses["picture_atoms"] == 2
    assert senses["picture_bytes_missing"] == 1


def test_the_http_surface_is_exactly_what_someone_uses() -> None:
    """A route nobody calls is a contract nobody keeps: adding one has to be a deliberate act."""
    served = {
        route.path
        for route in api_module.app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api")
    }
    assert served == HTTP_SURFACE
