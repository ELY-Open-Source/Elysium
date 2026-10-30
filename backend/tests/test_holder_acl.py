"""The sharing rule over HTTP: a token says who is asking, and the store answers to that person."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import elysian.api as api_module
from elysian.compiler import ContextCompiler
from elysian.config import Settings
from elysian.db import Database
from elysian.holder_store import HolderStore
from elysian.memory import MemoryService
from elysian.schemas import (
    EvidenceAtom,
    MemoryOrigin,
    Modality,
    RuntimeProfile,
    SourceRecord,
    TrustScores,
    Visibility,
)
from elysian.storage import ObjectStore

OPERATOR = "the-operator-token"
AS_OPERATOR = {"Authorization": f"Bearer {OPERATOR}"}
PNG = b"\x89PNG\r\n\x1a\n"
KEYS = "我们的钥匙放在玄关抽屉里"
THERMOSTAT = "恒温器设在二十二度"
OUTAGE = "上周三的停电持续了四十分钟"


def _settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    resolved = Settings(home=tmp_path, default_holder="wife", auth_token=OPERATOR)
    monkeypatch.setattr(api_module, "get_settings", lambda: resolved)
    Database(resolved).init()
    return resolved


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(api_module.create_app())


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    return _settings(tmp_path, monkeypatch)


def _token_for(client: TestClient, holder_id: str) -> dict[str, Any]:
    answer = client.post(f"/api/holders/{holder_id}/token", headers=AS_OPERATOR)
    assert answer.status_code == 200, answer.json()
    return dict(answer.json())


def _remember(settings: Settings, text: str, holder_id: str, **kwargs: Any) -> EvidenceAtom:
    return MemoryService(settings, Database(settings)).remember(
        text, holder_id=holder_id, origin=MemoryOrigin.self_, **kwargs
    )


def _hits(client: TestClient, query: str, headers: dict[str, str] | None = None, **body: Any) -> list[str]:
    answer = client.post("/api/search", json={"query": query, **body}, headers=headers or {})
    assert answer.status_code == 200, answer.json()
    return [str(hit["atom"]["atom_id"]) for hit in answer.json()["hits"]]


def test_only_the_operator_mints_a_token(client: TestClient, settings: Settings) -> None:
    _remember(settings, KEYS, "wife")
    wife = _token_for(client, "wife")
    assert client.post("/api/holders/husband/token").status_code == 401, "no token cannot mint one"
    refused = client.post("/api/holders/husband/token", headers={"Authorization": f"Bearer {wife['token']}"})
    assert refused.status_code == 401, "a holder token is not an operator token"
    assert "Bearer" in refused.json()["detail"]


def test_the_token_is_shown_once_and_stored_as_a_hash(client: TestClient, settings: Settings) -> None:
    _remember(settings, KEYS, "wife")
    issued = _token_for(client, "wife")
    token = str(issued["token"])
    assert issued["holder_id"] == "wife" and issued["issued_at"]

    with Database(settings).connect() as connection:
        row = connection.execute("SELECT token_hash FROM holders WHERE holder_id = 'wife'").fetchone()
    stored = str(row["token_hash"])
    assert stored == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert token not in stored and len(stored) == 64, "a copied database must not replay the token"

    listed = client.get("/api/holders/wife", headers=AS_OPERATOR).json()
    assert "token" not in listed and listed["token_issued_at"] == issued["issued_at"]


def test_a_holder_token_reads_as_that_holder_and_nobody_else(client: TestClient, settings: Settings) -> None:
    mine = _remember(settings, KEYS, "wife")
    wife = _token_for(client, "wife")
    _token_for(client, "husband")

    as_wife = _hits(client, KEYS, headers={"Authorization": f"Bearer {wife['token']}"})
    as_husband = _hits(client, KEYS, headers={"Authorization": f"Bearer {wife['token']}"})
    assert mine.atom_id in as_wife
    assert as_husband == as_wife, "the same token reads the same way whatever the query says"

    anonymous = _hits(client, KEYS)
    assert mine.atom_id not in anonymous, "a caller with no token is nobody"


def test_an_unknown_token_is_refused_rather_than_treated_as_nobody(client: TestClient, settings: Settings) -> None:
    _remember(settings, KEYS, "wife")
    refused = client.post("/api/search", json={"query": KEYS}, headers={"Authorization": "Bearer not-a-token"})
    assert refused.status_code == 401
    detail = str(refused.json()["detail"])
    assert "operator" in detail and "holder" in detail, "the refusal has to say which two things failed"


def test_a_public_memory_is_findable_by_anybody(client: TestClient, settings: Settings) -> None:
    shared = _remember(settings, OUTAGE, "wife", visibility=Visibility(scope="everyone"))
    assert shared.atom_id in _hits(client, OUTAGE), "no token, still visible"


def test_a_shared_memory_is_readable_only_by_the_holders_it_names(client: TestClient, settings: Settings) -> None:
    private = _remember(settings, THERMOSTAT, "wife", visibility=Visibility(scope="visible_to", holders=["husband"]))
    _remember(settings, KEYS, "husband")
    wife = _token_for(client, "wife")
    husband = _token_for(client, "husband")

    assert private.atom_id in _hits(client, THERMOSTAT, headers={"Authorization": f"Bearer {husband['token']}"})
    assert private.atom_id in _hits(client, THERMOSTAT, headers={"Authorization": f"Bearer {wife['token']}"})
    assert private.atom_id not in _hits(client, THERMOSTAT)

    outsider = _remember(settings, OUTAGE, "neighbour")
    _token_for(client, "neighbour")
    neighbour = _token_for(client, "neighbour")
    assert outsider.atom_id
    assert private.atom_id not in _hits(client, THERMOSTAT, headers={"Authorization": f"Bearer {neighbour['token']}"})


def test_naming_another_holder_is_a_claim_the_token_has_to_back(client: TestClient, settings: Settings) -> None:
    mine = _remember(settings, KEYS, "wife")
    wife = _token_for(client, "wife")
    _token_for(client, "husband")
    as_wife = {"Authorization": f"Bearer {wife['token']}"}

    over = client.post("/api/search", json={"query": KEYS, "filters": {"as_holder": "husband"}}, headers=as_wife)
    assert over.status_code == 403
    detail = str(over.json()["detail"])
    assert "wife" in detail and "husband" in detail, "a refusal that names neither side cannot be acted on"

    anonymous = client.post("/api/search", json={"query": KEYS, "filters": {"as_holder": "wife"}})
    assert anonymous.status_code == 403, "typing a name is not a token"

    operator = client.post("/api/search", json={"query": KEYS, "filters": {"as_holder": "wife"}}, headers=AS_OPERATOR)
    assert operator.status_code == 200
    assert mine.atom_id in [str(hit["atom"]["atom_id"]) for hit in operator.json()["hits"]]


def test_revoking_a_token_stops_it_working(client: TestClient, settings: Settings) -> None:
    _remember(settings, KEYS, "wife")
    token = _token_for(client, "wife")["token"]
    assert HolderStore(Database(settings)).verify_token(str(token)) == "wife"

    revoked = client.delete("/api/holders/wife/token", headers=AS_OPERATOR)
    assert revoked.status_code == 200 and revoked.json()["holder_id"] == "wife"
    assert client.post("/api/search", json={"query": KEYS}, headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.get("/api/holders/wife", headers=AS_OPERATOR).json()["token_issued_at"] is None


def test_a_working_set_refuses_to_belong_to_nobody(client: TestClient, settings: Settings) -> None:
    _remember(settings, KEYS, "wife", session_id="kitchen-2026")
    _remember(settings, THERMOSTAT, "husband", session_id="kitchen-2026")

    anonymous = client.get("/api/memory/working", params={"session": "kitchen-2026"})
    assert anonymous.status_code == 422
    assert "somebody" in str(anonymous.json()["detail"])

    wife = _token_for(client, "wife")
    hers = client.get("/api/memory/working", params={"session": "kitchen-2026"}, headers={"Authorization": f"Bearer {wife['token']}"})
    assert [atom["text"] for atom in hers.json()] == [KEYS], "a session sees its own lane, not the room's"

    both = client.get("/api/memory/working", params={"session": "kitchen-2026", "holder": "husband"}, headers=AS_OPERATOR)
    assert [atom["text"] for atom in both.json()] == [THERMOSTAT]


def test_a_conflict_list_refuses_to_belong_to_nobody(client: TestClient, settings: Settings) -> None:
    _remember(settings, "恒温器放在书房，设定 22 度", "wife")
    _remember(settings, "恒温器调到 24 度", "wife")
    assert client.get("/api/memory/conflicts").status_code == 422
    wife = _token_for(client, "wife")
    hers = client.get("/api/memory/conflicts", headers={"Authorization": f"Bearer {wife['token']}"})
    assert hers.status_code == 200 and len(hers.json()) == 1


def test_the_card_is_public_names_holders_and_carries_no_memory_text(client: TestClient, settings: Settings) -> None:
    _remember(settings, KEYS, "wife", scenario="home")
    _remember(settings, THERMOSTAT, "husband")
    _token_for(client, "wife")

    answer = client.get("/api/card")
    assert answer.status_code == 200, "a capability card exists to be read by a stranger"
    card = answer.json()
    assert card["schema_version"] >= 11 and card["has_audio"] is False
    named = {holder["holder_id"]: holder for holder in card["holders"]}
    assert set(named) == {"wife", "husband"}
    assert named["wife"]["memories"] == 1 and named["wife"]["token_issued"] is True
    assert named["husband"]["token_issued"] is False
    assert named["wife"]["scenarios"] == ["home"] and named["wife"]["modalities"] == {"text": 1}
    assert named["wife"]["newest_memory"], "a stranger needs to know how stale the memory is"
    assert KEYS not in answer.text and THERMOSTAT not in answer.text

    one = client.get("/api/card/wife")
    assert one.status_code == 200 and one.json()["holder_id"] == "wife"
    assert client.get("/api/card/nobody").status_code == 404


def test_a_picture_is_served_only_to_eyes_that_may_see_it(client: TestClient, settings: Settings) -> None:
    database = Database(settings)
    stored = ObjectStore(settings).put_bytes(PNG, ".png", "image")
    database.upsert_sources(
        [
            SourceRecord(
                source_id=source,
                path=f"file:///{source}.png",
                kind="image",
                mime="image/png",
                sha256=source * 8,
                size_bytes=len(PNG),
            )
            for source in ("hers", "ours")
        ]
    )
    database.upsert_atoms(
        [
            EvidenceAtom(
                atom_id=f"{source}:frame",
                modality=Modality.image,
                source_id=source,
                source=f"file:///{source}.png",
                image_ref=stored,
                trust=TrustScores(parser=1.0, ocr=0.0, model=0.0),
                holder_id="wife" if source == "hers" else "",
            )
            for source in ("hers", "ours")
        ]
    )

    assert client.get("/api/atoms/ours:frame/image").status_code == 200, "nobody owns it, so anybody may look"
    assert client.get("/api/atoms/hers:frame/image").status_code == 404, "the bytes are behind the same rule as the words"
    assert client.get("/api/atoms", params={"modality": "image"}).json()["total"] == 1
    wife = _token_for(client, "wife")
    page = client.get("/api/atoms", params={"modality": "image"}, headers={"Authorization": f"Bearer {wife['token']}"})
    assert page.json()["total"] == 2


def test_an_operator_and_a_stranger_do_not_share_one_compiled_context(settings: Settings) -> None:
    _remember(settings, KEYS, "wife")
    compiler = ContextCompiler(settings, Database(settings))
    # The stranger compiles first: if the cache key ignored whose eyes were used, the operator would be served this.
    stranger = compiler.compile(KEYS, RuntimeProfile.live_demo, as_holder="")
    assert stranger.hits == [], "a memory nobody owns and nobody marked public is invisible to a stranger"

    owner = compiler.compile(KEYS, RuntimeProfile.live_demo, as_holder="wife")
    assert KEYS in owner.packed_text and owner.cache_trace_id != stranger.cache_trace_id

    whole = compiler.compile(KEYS, RuntimeProfile.live_demo)
    assert KEYS in whole.packed_text, "a process that owns the store still reads the whole library"
