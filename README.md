# Elysium · 往世乐土

Elysium (Chinese name 往世乐土) is a local memory store for AI. Every memory it keeps carries who it
belongs to, where it came from, when it was true, in what situation, and who may
read it. Retrieval answers as the person asking, so a store shared by several
people and several agents does not blend them into one voice. A Context
Cartridge is a scope you mount, not only a bundle you export. Coding agents
reach the same store over MCP.

The difference between this and a vector database is the referral: "I don't know
where the keys are, I know my wife knows, and I can find my wife." When the
store cannot answer, it says nobody knows and names who does — instead of
inventing a plausible answer.

Everything below is either measured in this repository, with the report and the
command that re-measures it, or it is marked as not measured.

## What is measured

| question | answer | report |
| --- | --- | --- |
| can it find the memory that answers a question? | recall@10 **0.863**, MRR 0.682, over 300 answerable probes drawn from six third-party corpora, each asked as the holder that corpus assigns it | `bench/reports/LEGS.md` |
| is that any good? | a Mem0-style counterpart on the same corpus scores **0.866** inside one holder's memory and **0.412** across all of them; chance is 0.0002 whole-corpus and 0.369 inside one holder | `bench/reports/BASELINE_EXTERNAL.md` |
| does the holder boundary matter? | **+0.454 recall@10** with an identical ranker and identical items — the gain is scoping, not ranking | same report |
| how fast at corpus size? | p50 **0.072 s**, p95 0.218 s over 165,973 atoms; the search this replaced took 20.16 s on the same corpus | `bench/reports/SCALE.md` |
| how much does it hold? | 165,973 atoms and 153,857 vectors in one SQLite file; the vector build runs 106 memories/s. One million is an extrapolation, not a measurement | `bench/reports/DENSE.md` |
| can a wordless picture be found? | yes for icon crops, weakly for whole screenshots — the report shows every arm, including the ones that hurt | `bench/reports/VISUAL.md` |
| what does speech cost? | WER **0.242** over 533 reference words; 258.18 s of audio transcribed in 3.12 s (68.4–111.2× realtime per video, CPU int8), byte-identical across two passes | `bench/reports/ASR.md` |
| is the acceptance bar met? | **no.** The bar is recall@10 ≥ 0.90; shipped is 0.863 | `bench/reports/LEGS.md` |

Where the deficit lives, by modality (recall@10, same run): code 0.945,
conversation 1.000, pdf 0.885, ui_screenshot 0.818, image 0.720, video 0.455.
Video is the worst because the frozen stores hold no audio atoms — a video is
sampled frames plus OCR, so a question answered by speech has nothing to match.
Images and screenshots are limited because CLIP cannot localize an icon inside a
screenshot. `bench/reports/LEGS.md` names the arms; nothing here rounds those
numbers up.

Re-measure any of them:

```bash
python -m bench.validate_sets                      # the frozen corpus and its gold
python -m bench.leg_check --probes 300             # the shipped retrieval path
python -m bench.run_external                       # the counterparts and the chance floor
python -m bench.dense_scale                        # the vector leg at corpus size
```

## What is not measured here

The generator side is written and runnable but has not been run in this
repository's reports, so no score from it is quoted anywhere in this README:

- generation with Qwen3.5-9B and the trained LoRA adapters — `elysium runtime-generation-proof`
- Visual HashHop multi-hop visual addressing — `elysium hashhop --kind visual`
- the Visual Contradiction Lens — `elysium visual-contradiction-proof`
- standard benchmarks (MMMU-Pro, OCRBench, and the rest) — `elysium run-benchmark`
- the fifteen-check proof suite as a whole — `elysium proof-suite`

Each needs a CUDA machine and a model download. They are marked DEFERRED in
`CHECKLIST.md`, and a run that has not happened is not allowed to look like a
result: `elysium proof-suite` writes what it observed, and the checks that
depend on a model report what they could not do rather than passing quietly.

`TRAINING_ARTIFACTS.md` keeps the six-adapter training table, which is
artifact-backed on the machine that trained them, and no longer quotes benchmark
scores that were never run.

## What a memory carries

`holder_id`, `origin` (self / observed / artifact / third_party), `scenario`,
`event_time` with its precision and how it was learned, `valid_from` /
`valid_to`, `supersedes`, `visibility` (holder / visible_to / everyone),
`retention_until`, plus ingestion time and trust scores. Ingestion stamps
provenance; a client cannot claim to be somebody else, because the server
decides who a caller is from the token it presents.

Four verbs, one writer: `remember`, `supersede`, `forget`, `search`. They exist
over HTTP, the CLI, and MCP, and they all go through the same Python writer, so
the rules cannot drift apart. `forget` cascades to everything derived — vectors,
FTS rows, edges, cache entries — and reports which cartridges contained the
memory rather than silently rewriting an export whose digest somebody already
quoted.

On top of that: a working tier (what one session recorded, in order),
consolidation into a standing summary, an archive tier for memories that are
neither used nor valued, and a conflict list for dated memories that disagree
and that nobody has settled. A third-party memory that no other memory vouches
for is quarantined: it stays in the store, and it is not citable.

## Run it

Linux and macOS:

```bash
bash scripts/install.sh
bash scripts/serve-backend.sh          # API on http://127.0.0.1:8765
bash scripts/serve-frontend.sh         # dashboard on http://127.0.0.1:5173
```

Windows: the same names as `.ps1`. There is also a container image
(`docker build -t elysium .`), and CI runs the whole suite on Linux.

```bash
elysium ingest ~/some/package --cartridge-name project
elysium search "where did we put the archive key" --as-holder wife
elysium remember "the archive key is in the second drawer" --holder wife --scenario home
elysium who-knows "archive key"
elysium ask "where is the archive key" --as-holder husband
elysium card
elysium mounts && elysium mount project && elysium unmount
elysium backup ./backup && elysium doctor
bash scripts/mcp_write_smoke.sh        # two processes, one store, one SQLite
```

The dashboard is served by the API itself once `ELYSIUM_UI_DIR` points at
`frontend/dist`. `scripts/ui_smoke.sh` drives it in a real browser against a
fresh store and fails if any of it stops working. The CLI does everything the
console does, so nothing requires a browser.

## Retrieval

Three legs, fused by rank. The words leg always runs. The dense leg runs only
when `ELYSIUM_DENSE_EMBEDDINGS_ENABLED=1` and an embedding model is configured.
On the shipped page that leg moves recall from 0.863 to 0.860 while p50 goes
from 122 ms to 713 ms; on a wider page both reach 0.873 while p50 goes from
84 ms to 579 ms. It buys the memory questions (multi-session 0.857 → 0.920,
preference 0.800 → 0.960) and costs the picture ones (image 0.720 → 0.680),
which is why it is opt-in rather than the default. The picture leg runs only
when the words page comes back thin and `ELYSIUM_CLIP_MODEL_DIR` is set.
Vectors live in the database beside the atoms, written in the same transaction
as the memory itself, so a memory is findable the moment it is stored and there
is no index to rebuild.

## MCP server for coding agents

`elysium-mcp/` is a Go MCP server. One command builds a native binary and
registers it with Codex and Claude Code. Reads mirror the store; writes go
through the API, so the write rules live in one place. A read with no
`ELYSIUM_AUTH_TOKEN` sees only memories nobody owns and memories marked for
everyone; `elysium_card` answers "can this store answer my kind of question"
before anything sensitive is sent, and it carries no memory text.

```bash
bash ./elysium-mcp/install.sh --client both
```

See `elysium-mcp/README.md` for the full tool list.

## Data layout

Runtime state lives under `.elysium/` (git-ignored):

```text
.elysium/
├─ data/         the SQLite store: atoms, FTS, vectors (vec0), edges, mounts
├─ objects/      ingested source files
├─ cache/        compiled-context cache and the picture index
├─ cartridges/   materialized Context Cartridges
├─ adapters/     trained LoRA adapters
└─ training/     datasets and training traces
```

A Context Cartridge is a self-contained memory package: the Evidence Atoms, the
sparse and vector indexes, the temporal graph, and a DNA digest of the files.
Mounting one scopes every subsequent search to it; switching is one command.

## Project layout

```text
backend/     Python: ingestion, retrieval, memory, runtime, training, FastAPI
bench/       the benchmark suite: frozen third-party corpora, harnesses, reports
frontend/    the local dashboard (Vite + React)
scripts/     install, serving, runtimes, smoke (.sh on Linux/macOS, .ps1 on Windows)
elysium-mcp/ Go: the MCP server
```

`CHECKLIST.md` is the ordered work list with the acceptance line for every item;
`Gaps.md` is the audit this work started from.

## License

AGPL-3.0-only. Copyright © 2026 雷电芽衣 <zhangyanghaha0407@outlook.com>.

The PDF reader (PyMuPDF) is dual-licensed under AGPL-3.0 or an Artifex
Commercial license, so this project ships under AGPL while that dependency is
in use. Buying the Artifex license is what would allow a permissive one.
