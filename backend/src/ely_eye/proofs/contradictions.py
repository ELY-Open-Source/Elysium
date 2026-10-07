"""Contradiction scenarios and the lens that has to spot them.

The scenarios are data, not code: the proof loads them from a JSON corpus so the set that grades
the lens is reviewable, replaceable, and named by hash in the proof artifact.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..schemas import (
    CompiledContext,
    ContextPlan,
    EvidenceAtom,
    Modality,
    RetrievalHit,
    RuntimeProfile,
    TrustScores,
)

CORPUS_NAME = "contradiction_scenarios.json"
PACKAGED_CORPUS = Path(__file__).with_name(CORPUS_NAME)


def contradiction_atom(
    atom_id: str,
    source_id: str,
    source: str,
    text: str,
    modality: Modality,
    source_kind: str,
    version: str | None = None,
) -> EvidenceAtom:
    metadata: dict[str, Any] = {"source_kind": source_kind}
    if version is not None:
        metadata["version"] = version
    return EvidenceAtom(
        atom_id=atom_id,
        modality=modality,
        source_id=source_id,
        source=source,
        text=text,
        trust=TrustScores(parser=0.95, ocr=0.9, model=0.85),
        token_equivalent=max(1, len(text) // 4),
        metadata=metadata,
    )


def contradiction_context(question: str, atoms: list[EvidenceAtom]) -> CompiledContext:
    hits = [
        RetrievalHit(atom=atom, sparse_score=0.8, dense_score=0.0, graph_score=0.0, final_score=0.8)
        for atom in atoms
    ]
    plan = ContextPlan(
        question=question,
        profile=RuntimeProfile.research_theater,
        required_modalities=sorted({atom.modality for atom in atoms}),
        evidence_budget_atoms=len(atoms),
        token_budget=sum(atom.token_equivalent for atom in atoms),
        retrieval_query=question,
        compression_strategy="visual-contradiction-eval",
        verifier_contract=["Report contradictions as contradiction_notes."],
    )
    packed = "\n".join(f"[{atom.atom_id}] {atom.text}" for atom in atoms)
    return CompiledContext(
        plan=plan,
        hits=hits,
        packed_text=packed,
        token_equivalent=sum(atom.token_equivalent for atom in atoms),
        cache_trace_id="visual_contradiction_eval",
    )


def build_contradiction_scenarios() -> list[dict[str, Any]]:
    """Deterministic cross-version conflict and control samples (PRD 11.15).

    Each conflict pair injects a single genuine drift across two distinct
    sources; each control pair is internally consistent or scoped to different
    components. The samples exercise the live ``VisualContradictionLens`` so the
    proof measures real recall and false-positive rate.

    A scenario carries its atoms and its label; the compiled context the lens reads is built at
    use, so the corpus on disk holds no derived state.
    """

    scenarios: list[dict[str, Any]] = []

    def conflict(name: str, atoms: list[EvidenceAtom]) -> None:
        scenarios.append({"name": name, "atoms": atoms, "expect_drift": True})

    def control(name: str, atoms: list[EvidenceAtom]) -> None:
        scenarios.append({"name": name, "atoms": atoms, "expect_drift": False})

    conflict(
        "button-radius-token-drift",
        [
            contradiction_atom("home_btn_v4", "home_v4", "home_v4.figma", "button.radius: 8px", Modality.ui_screenshot, "figma"),
            contradiction_atom("checkout_btn_v4", "checkout_v4", "checkout_v4.figma", "button.radius: 12px", Modality.ui_screenshot, "figma"),
        ],
    )
    conflict(
        "primary-color-token-drift",
        [
            contradiction_atom("spec_color", "brand_spec", "brand_guide.pdf", "primary.color: #2563eb", Modality.pdf_page, "spec"),
            contradiction_atom("impl_color", "theme_css", "src/theme.css", "primary.color: #1d4ed8", Modality.code, "css"),
        ],
    )
    conflict(
        "heading-typography-drift",
        [
            contradiction_atom("home_heading", "home_shot", "home_v3.png", "heading.font-size: 24px", Modality.ui_screenshot, "ui_screenshot"),
            contradiction_atom("checkout_heading", "checkout_shot", "checkout_v3.png", "heading.font-size: 28px", Modality.ui_screenshot, "ui_screenshot"),
        ],
    )
    conflict(
        "card-spacing-layout-drift",
        [
            contradiction_atom("card_home", "card_home_shot", "home_v3.png", "card.padding: 16px", Modality.ui_screenshot, "ui_screenshot"),
            contradiction_atom("card_settings", "card_settings_shot", "settings_v3.png", "card.padding: 24px", Modality.ui_screenshot, "ui_screenshot"),
        ],
    )
    conflict(
        "cta-copy-drift",
        [
            contradiction_atom("cta_v1", "shot_v1", "cart_v1.png", 'cta.label: "Checkout"', Modality.ui_screenshot, "ui_screenshot"),
            contradiction_atom("cta_v4", "shot_v4", "cart_v4.png", 'cta.label: "Pay now"', Modality.ui_screenshot, "ui_screenshot"),
        ],
    )
    conflict(
        "banner-radius-temporal-drift",
        [
            contradiction_atom("banner_v1", "banner_spec_v1", "banner_v1.figma", "banner.radius: 4px", Modality.ui_screenshot, "figma", version="v1"),
            contradiction_atom("banner_v4", "banner_spec_v4", "banner_v4.figma", "banner.radius: 10px", Modality.ui_screenshot, "figma", version="v4"),
        ],
    )
    conflict(
        "toggle-accent-visual-code-drift",
        [
            contradiction_atom("toggle_design", "toggle_figma", "toggle.figma", "toggle.color: #10b981", Modality.ui_screenshot, "figma"),
            contradiction_atom("toggle_code", "toggle_css", "src/toggle.css", "toggle.color: #059669", Modality.code, "css"),
        ],
    )

    control(
        "consistent-button-radius",
        [
            contradiction_atom("ctrl_btn_spec", "ctrl_spec", "spec.pdf", "button.radius: 8px", Modality.pdf_page, "spec"),
            contradiction_atom("ctrl_btn_css", "ctrl_css", "src/tokens.css", "button.radius = 8px", Modality.code, "css"),
        ],
    )
    control(
        "distinct-components-not-a-conflict",
        [
            contradiction_atom("ctrl_button_radius", "ctrl_a", "a.css", "button.radius: 8px", Modality.code, "css"),
            contradiction_atom("ctrl_input_radius", "ctrl_b", "b.css", "input.radius: 12px", Modality.code, "css"),
        ],
    )
    control(
        "single-source-multiple-rules",
        [
            contradiction_atom(
                "ctrl_single_css",
                "ctrl_single",
                "src/base.css",
                "header.padding: 8px; footer.padding: 24px; aside.padding: 16px",
                Modality.code,
                "css",
            ),
        ],
    )
    control(
        "consistent-primary-color",
        [
            contradiction_atom("ctrl_color_spec", "ctrl_color_a", "brand.pdf", "primary.color: #2563eb", Modality.pdf_page, "spec"),
            contradiction_atom("ctrl_color_css", "ctrl_color_b", "theme.css", "primary.color: #2563eb", Modality.code, "css"),
        ],
    )
    control(
        "prose-without-design-facts",
        [
            contradiction_atom("ctrl_prose_a", "ctrl_prose_1", "notes_a.txt", "The onboarding flow feels smooth and the colors look balanced.", Modality.text, "text"),
            contradiction_atom("ctrl_prose_b", "ctrl_prose_2", "notes_b.txt", "Users reported the checkout button is easy to find.", Modality.text, "text"),
        ],
    )

    return scenarios


def corpus_path(data_dir: Path) -> Path | None:
    """A corpus the operator dropped in beats the packaged one; neither beats silence."""
    override = data_dir / CORPUS_NAME
    if override.exists():
        return override
    return PACKAGED_CORPUS if PACKAGED_CORPUS.exists() else None


def write_corpus(path: Path) -> Path:
    """Freeze the generated scenarios as data so the grader can be read, not just run."""
    payload = [
        {"name": scenario["name"], "expect_drift": scenario["expect_drift"], "atoms": [atom.model_dump(mode="json") for atom in scenario["atoms"]]}
        for scenario in build_contradiction_scenarios()
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_corpus(path: Path) -> tuple[list[dict[str, Any]], str]:
    """Read the corpus and its hash. A scenario whose label cannot be parsed fails loudly."""
    try:
        raw = path.read_bytes()
        rows = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{path}: the contradiction corpus is unreadable ({error})") from error
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path}: the contradiction corpus must be a non-empty list")
    scenarios: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or "name" not in row or "expect_drift" not in row:
            raise ValueError(f"{path}: a contradiction scenario is missing its name or its label")
        try:
            atoms = [EvidenceAtom.model_validate(entry) for entry in row.get("atoms", [])]
        except ValueError as error:
            raise ValueError(f"{path}: scenario {row['name']!r} holds an unreadable atom ({error})") from error
        if not atoms:
            raise ValueError(f"{path}: scenario {row['name']!r} has no atoms to compare")
        scenarios.append({"name": row["name"], "expect_drift": bool(row["expect_drift"]), "atoms": atoms})
    return scenarios, hashlib.sha256(raw).hexdigest()


def scenario_context(scenario: dict[str, Any]) -> CompiledContext:
    return contradiction_context(str(scenario["name"]), scenario["atoms"])
