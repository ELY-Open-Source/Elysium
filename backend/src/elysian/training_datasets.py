"""Turn a store and a PRD into the SFT and retrieval datasets the adapters train on."""

from __future__ import annotations

from pathlib import Path

from .config import Settings
from .db import Database
from .schemas import EvidenceAtom, TrainingAdapterKind
from .training_common import (
    TrainingSample,
    section_by_title,
    sha256_bytes,
    slugify,
    split_markdown_sections,
    write_jsonl,
)
from .training_encode import compact_text, prepare_training_image, render_prd_training_card


def validate_dataset(path: Path) -> list[TrainingSample]:
    samples: list[TrainingSample] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                samples.append(TrainingSample.model_validate_json(line))
            except Exception as exc:
                raise ValueError(f"Invalid training sample at line {line_number}: {exc}") from exc
    if not samples:
        raise ValueError(f"Training dataset is empty: {path}")
    return samples

def atoms_for_path(database: Database, path: Path) -> list[EvidenceAtom]:
    resolved = path.resolve()
    atoms: list[EvidenceAtom] = []
    for atom in database.list_atoms():
        try:
            if Path(atom.source).resolve() == resolved:
                atoms.append(atom)
        except OSError:
            if atom.source == str(path):
                atoms.append(atom)
    return atoms

def atom_id_for_path(database: Database, path: Path, text: str) -> str:
    atoms = atoms_for_path(database, path)
    return atoms[0].atom_id if atoms else f"{path.stem}:{sha256_bytes(text.encode('utf-8'))[:12]}"

def latest_cartridge_id(database: Database) -> str | None:
    rows = database.list_cartridges()
    return str(rows[0]["cartridge_id"]) if rows else None

def model_for_kind(settings: Settings, kind: TrainingAdapterKind) -> str:
    if kind == TrainingAdapterKind.hme_router:
        return settings.planner_model_id
    return settings.model_id

def build_prd_dataset(
    settings: Settings,
    database: Database,
    prd_path: Path,
    output_path: Path | None = None,
    cartridge_id: str | None = None,
    max_sections: int = 48,
) -> Path:
    prd_path = prd_path.resolve()
    text = prd_path.read_text(encoding="utf-8")
    atoms = atoms_for_path(database, prd_path)
    atom_id = atoms[0].atom_id if atoms else f"{prd_path.stem}:{sha256_bytes(text.encode('utf-8'))[:12]}"
    cartridge_id = cartridge_id or latest_cartridge_id(database)
    sections = split_markdown_sections(text)
    if not sections:
        raise ValueError(f"No markdown sections found in {prd_path}")
    output_path = output_path or (settings.training_dir / "hme_prd_sft.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    samples: list[TrainingSample] = []
    for index, section in enumerate(sections[:max_sections], start=1):
        title = section["title"]
        body = compact_text(section["body"], limit=5200)
        if len(body) < 160:
            continue
        citation = f"{atom_id}#section={slugify(title)}"
        answer = compact_text(body, limit=900)
        samples.append(
            TrainingSample(
                id=f"hme_prd_{index:04d}",
                task="hme_core_lora_evidence_json",
                inputs=[
                    {
                        "type": "text",
                        "text": (
                            f"Section title: {title}\n"
                            f"Evidence atom: {atom_id}\n"
                            f"Evidence:\n{body}\n\n"
                            "Question: State the Elysian requirement in this section. "
                            "Return JSON with answer, citations, contradiction_notes, confidence."
                        ),
                    }
                ],
                memory={
                    "cartridge": cartridge_id,
                    "required_atoms": [atom_id],
                    "source": str(prd_path),
                },
                output={
                    "answer": answer,
                    "citations": [citation],
                    "contradiction_notes": [],
                    "confidence": 1.0,
                    "reasoning_policy": "evidence-first",
                },
            )
        )

    if not samples:
        raise ValueError(f"No usable PRD training sections found in {prd_path}")
    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for sample in samples:
            handle.write(sample.model_dump_json() + "\n")
    return output_path

def build_visual_dataset(
    settings: Settings,
    database: Database,
    prd_path: Path,
    output_path: Path | None = None,
    image_paths: list[Path] | None = None,
    cartridge_id: str | None = None,
) -> Path:
    prd_path = prd_path.resolve()
    text = prd_path.read_text(encoding="utf-8")
    atom_id = atom_id_for_path(database, prd_path, text)
    cartridge_id = cartridge_id or latest_cartridge_id(database)
    media_dir = settings.training_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    prepared_images: list[Path] = []
    for image_path in image_paths or []:
        if image_path.exists():
            prepared_images.append(prepare_training_image(image_path, media_dir))
    prd_card = render_prd_training_card(text, atom_id, media_dir / "prd_training_card.png")
    prepared_images.append(prd_card)
    if not prepared_images:
        raise ValueError("No visual training images are available")

    output_path = output_path or (settings.training_dir / "hme_visual_sft.jsonl")
    samples: list[TrainingSample] = []
    visual_tasks = [
        (
            "hme_vision_lora_visual_grounding",
            "12.1 训练目标",
            (
                "Elysian trains HME-Vision-LoRA on Qwen3.5-9B vision projector "
                "and selected vision layers so UI, PDF, OCR, and chart evidence can be "
                "grounded into cited multimodal memory."
            ),
        ),
        (
            "hme_ttt_vl_visual_memory",
            "11.2 X — TTT-VL：视觉语言测试时学习",
            (
                "TTT-VL keeps Qwen3.5-9B frozen while mutable MLP and visual LoRA "
                "adapters learn low-step visual memory updates that can be consolidated "
                "into cartridge-local adapter deltas."
            ),
        ),
        (
            "hme_visual_hashhop_grounding",
            "11.3 X — Visual HashHop",
            (
                "Visual HashHop converts random chain ids into non-text geometric image "
                "blocks, then evaluates long-range visual addressing without OCR shortcuts."
            ),
        ),
        (
            "hme_dvkv_visual_cache",
            "11.4 S/H — DVKV：Diversity-Aware Visual KV Compression",
            (
                "DVKV keeps visual KV tokens by combining attention importance, visual "
                "diversity, and evidence value so OCR, layout, chart, and coordinate details "
                "survive compression."
            ),
        ),
        (
            "hme_visual_contradiction_lens",
            "11.15 X — Visual Contradiction Lens",
            (
                "The Visual Contradiction Lens compares visual versions and cites layout, "
                "design-token, copy, temporal, and visual-code drift as evidence graph facts."
            ),
        ),
    ]
    for index, image_path in enumerate(prepared_images, start=1):
        for task_index, (task, section_title, answer) in enumerate(visual_tasks, start=1):
            requirement = section_by_title(text, section_title)
            samples.append(
                TrainingSample(
                    id=f"hme_visual_{index:02d}_{task_index:02d}",
                    task=task,
                    inputs=[
                        {
                            "type": "ui_screenshot",
                            "path": str(image_path.resolve()),
                            "max_pixels": 262144,
                        },
                        {
                            "type": "text",
                            "text": (
                                f"Evidence atom: {atom_id}\n"
                                f"Visual source: {image_path.name}\n"
                                f"PRD visual requirement:\n"
                                f"{compact_text(requirement, 2200)}\n\n"
                                "Question: Map this visual evidence to the Elysian PRD module. "
                                "Return JSON with answer, citations, contradiction_notes, confidence."
                            ),
                        },
                    ],
                    memory={
                        "cartridge": cartridge_id,
                        "required_atoms": [atom_id],
                        "source": str(prd_path),
                    },
                    output={
                        "answer": answer,
                        "citations": [f"{atom_id}#section={slugify(section_title)}"],
                        "contradiction_notes": [],
                        "confidence": 1.0,
                        "reasoning_policy": "evidence-first",
                    },
                )
            )
    write_jsonl(output_path, samples)
    return output_path

def build_router_dataset(
    settings: Settings,
    database: Database,
    prd_path: Path,
    output_path: Path | None = None,
    cartridge_id: str | None = None,
) -> Path:
    prd_path = prd_path.resolve()
    text = prd_path.read_text(encoding="utf-8")
    atom_id = atom_id_for_path(database, prd_path, text)
    cartridge_id = cartridge_id or latest_cartridge_id(database)
    output_path = output_path or (settings.training_dir / "hme_router_sft.jsonl")
    scenarios = [
        (
            "Summarize a stable live-demo answer from local PRD evidence.",
            "live_demo",
            262144,
            ["mixed"],
            "Prefix cache + sparse evidence packing",
        ),
        (
            "Plan a 1.01M extreme context run with YaRN and parked context.",
            "extreme_context",
            1010000,
            ["mixed"],
            "YaRN + V-NSA sparse blocks + DVKV visual KV compression + CPU/NVMe parked context",
        ),
        (
            "Route a 100M library question through Context Cartridge memory.",
            "library_100m",
            100000000,
            ["mixed"],
            "Context Cartridge retrieval + ColQwen-compatible dense vectors + BM25 + evidence graph pack",
        ),
        (
            "Audit UI screenshot and PRD differences for the research demo.",
            "research_theater",
            262144,
            ["image", "ui_screenshot"],
            "Visual patch cache + DVKV evidence-biased region retention",
        ),
        (
            "Find visual token compression methods across a 100M library cartridge.",
            "library_100m",
            100000000,
            ["pdf_page", "image", "video_frame"],
            "ColQwen-compatible retrieval + graph grouping + cited evidence pack",
        ),
        (
            "Compare UI versions and cite coordinates plus code evidence.",
            "research_theater",
            262144,
            ["ui_screenshot", "code", "text"],
            "Visual Contradiction Lens + evidence graph writeback",
        ),
        (
            "Run Visual HashHop at 262K with a two-hop random image chain.",
            "research_theater",
            262144,
            ["image"],
            "Visual HashHop arena + verifier contract + no OCR-dependent evidence",
        ),
        (
            "Answer from a TTT-VL cartridge after original images are absent.",
            "library_100m",
            100000000,
            ["mixed"],
            "Load cartridge adapters + learned memory recall + cited adapter proof",
        ),
    ]
    samples = [
        TrainingSample(
            id=f"hme_router_{index:04d}",
            task="hme_router_context_plan",
            inputs=[
                {
                    "type": "text",
                    "text": (
                        f"Evidence atom: {atom_id}\n"
                        f"PRD routing source:\n{compact_text(section_by_title(text, '1. 产品定义'), 1800)}\n\n"
                        f"User request: {request}\n"
                        "Return the Elysian routing plan as compact JSON."
                    ),
                }
            ],
            memory={
                "cartridge": cartridge_id,
                "required_atoms": [atom_id],
                "source": str(prd_path),
            },
            output={
                "profile": profile,
                "token_budget": token_budget,
                "required_modalities": modalities,
                "retrieval_query": request,
                "compression_strategy": compression,
                "citations": [f"{atom_id}#section=1-产品定义"],
                "confidence": 1.0,
            },
        )
        for index, (request, profile, token_budget, modalities, compression) in enumerate(scenarios, start=1)
    ]
    write_jsonl(output_path, samples)
    return output_path

def build_retrieval_dataset(
    settings: Settings,
    database: Database,
    prd_path: Path,
    output_path: Path | None = None,
    cartridge_id: str | None = None,
    max_sections: int = 32,
) -> Path:
    prd_path = prd_path.resolve()
    text = prd_path.read_text(encoding="utf-8")
    atom_id = atom_id_for_path(database, prd_path, text)
    cartridge_id = cartridge_id or latest_cartridge_id(database)
    sections = [section for section in split_markdown_sections(text) if len(section["body"]) >= 160]
    output_path = output_path or (settings.training_dir / "hme_retrieval_pairs.jsonl")
    samples: list[TrainingSample] = []
    for index, section in enumerate(sections[:max_sections], start=1):
        title = section["title"]
        positive = compact_text(section["body"], 1600)
        samples.append(
            TrainingSample(
                id=f"hme_retrieval_{index:04d}",
                task="hme_retrieval_contrastive_pair",
                inputs=[
                    {
                        "type": "text",
                        "text": f"Find the PRD section that answers: {title}",
                    }
                ],
                memory={
                    "cartridge": cartridge_id,
                    "required_atoms": [atom_id],
                    "source": str(prd_path),
                },
                output={
                    "positive": positive,
                    "positive_title": title,
                    "citations": [f"{atom_id}#section={slugify(title)}"],
                    "confidence": 1.0,
                },
            )
        )
    if len(samples) < 2:
        raise ValueError("Retrieval contrastive training needs at least two PRD sections")
    write_jsonl(output_path, samples)
    return output_path
