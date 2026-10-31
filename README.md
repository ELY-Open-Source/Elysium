# Elysian · 往世乐土

Elysian (往世乐土) is a local memory store for AI. Every memory it keeps carries
who it belongs to, where it came from, when it was true, in what situation, and
who may read it. Retrieval answers as the person asking, so a store shared by several
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
| can it find the memory that answers a question? | recall@10 **0.901**, MRR 0.728, over all 2,928 answerable queries from six third-party corpora, each asked as the holder that corpus assigns it, with speech ingested and every picture described by a local Qwen3.5-9B (figures and screenshots at 512 tokens, video frames at 192); **0.916**, MRR 0.806, when the same 9B judges each returned page (`ELYSIAN_RERANK_BASE_URL`). Chance inside the asker's holder is 0.510 | `bench/reports/REDESCRIBE.md`, `bench/reports/RANK.md` |
| is that any good? | a Mem0-style counterpart on the same queries scores **0.866** inside one holder's memory and **0.412** across all of them; it was given the frozen stores' words, without descriptions or speech, and its own floor is 0.0002 whole-corpus and 0.369 inside one holder | `bench/reports/BASELINE_EXTERNAL.md` |
| and against the real Mem0? | on one pool of 110 test questions (619 sources, 1,963 items), with the same local 9B as every system's LLM: Elysian **0.864**, with the 9B judge **0.909** at 32,365 9B tokens a question; Mem0 2.2.1 storing raw text 0.891 at 23,087; Mem0 with its LLM extraction 0.718 at 228,116, and its LLM reranker leaves that at 0.718 with p50 15.6 s. Chance inside the asker's pool is 0.591. One run of 110 questions: raw Mem0 against Elysian without the judge is inside the noise | `bench/reports/LIVE.md`, `live_cost.svg` |
| does the holder boundary matter? | **+0.455 recall@10** with an identical ranker and identical items — the gain is scoping, not ranking | same report |
| how fast at corpus size? | p50 **0.072 s**, p95 0.218 s over 165,973 atoms; the search this replaced took 20.16 s on the same corpus. On today's 194,336-atom store the shipped search reads p50 0.14–0.16 s, p95 1.49–1.56 s (the holder-scope refill scans common words); with the judge p50 0.86–0.92 s, p95 2.05–2.48 s | `bench/reports/SCALE.md`, `bench/reports/redescribe.json` |
| how much does it hold? | 165,973 atoms and 153,857 vectors in one SQLite file; the vector build runs 106 memories/s. One million is an extrapolation, not a measurement | `bench/reports/DENSE.md` |
| can a wordless picture be found? | yes for icon crops, weakly for whole screenshots — the report shows every arm, including the ones that hurt | `bench/reports/VISUAL.md` |
| what does speech cost? | WER **0.242** over 533 reference words; 258.18 s of audio transcribed in 3.12 s (68.4–111.2× realtime per video, CPU int8), byte-identical across two passes | `bench/reports/ASR.md` |
| what is speech worth? | video recall@10 **0.493 → 0.651** over all 215 video questions, against a chance floor of 0.504 inside the asker's holder: frames and OCR alone ranked at chance, speech puts video 0.148 above it; the whole suite 0.848 → 0.857 against a holder-scoped floor of 0.510 | `bench/reports/VIDEO_AUDIO.md` |
| what did describing pictures give? | 0.857 → 0.877 with 192-token descriptions, 0.893 once a holder's search refills from every word when the rare ones run dry, 0.901 at 512 tokens; the judge adds 0.015 | `bench/reports/DESCRIBE.md`, `RANK.md`, `REDESCRIBE.md` |
| is the acceptance bar met? | **not at 0.92.** With the judge: whole suite 0.916 (hit@10 Wilson 95% lower 0.907), held-out test split 0.913, short by 0.004 and 0.007. Without it the older 0.90 bar holds on the whole suite (0.901) and misses on test (0.898) | `bench/reports/REDESCRIBE.md` |

Where the deficit lives, by modality (recall@10 with the judge, every answerable
query), each beside the chance floor of a random ranking inside the asker's
holder: code 0.977 (0.696), conversation 0.945 (0.210), pdf 0.898 (0.577),
image 0.863 (0.011), video 0.842 (0.504), ui_screenshot 0.800 (0.147). Of the
0.084 recall still missed, PDF holds 0.027, screenshots 0.022, video 0.012,
images 0.011, code 0.010 and conversation 0.003, weighted by how many questions
each holds. A described screenshot still misses an icon the description did not
name, and a video frame keeps its 192-token description; no UI widget tree is in
this repository. Nothing here rounds those numbers up.

Re-measure any of them:

```bash
python -m bench.validate_sets                      # the frozen corpus and its gold
python -m bench.leg_check --probes 300             # every leg, every answerable query
python -m bench.video_audio_check --speech-home bench/runs/video_audio_speech \
  --report /tmp/VIDEO_AUDIO.md --payload /tmp/video_audio.json   # speech; drop --speech-home to re-ingest (~5 h)
python -m bench.run_external                       # the counterparts and the chance floor
python -m bench.dense_scale                        # the vector leg at corpus size
ELYSIAN_VLM_BASE_URL=http://127.0.0.1:8001/v1 python -m bench.redescribe_check \
  --rerank-url http://127.0.0.1:8001/v1 \
  --report /tmp/REDESCRIBE.md --payload /tmp/redescribe.json   # descriptions at 512 tokens, shipped and judged
```

## What is not measured here

The generator side is written and runnable but has not been run in this
repository's reports, so no score from it is quoted anywhere in this README:

- generation with the trained LoRA adapters — `elysian runtime-generation-proof` (the base Qwen3.5-9B served by vLLM does run: key test 7 times its first token, `ELYSIAN_KEY_TEST_GENERATOR_URL=<vLLM /v1> bash scripts/key_test.sh`)
- Visual HashHop multi-hop visual addressing — `elysian hashhop --kind visual`
- the Visual Contradiction Lens — `elysian visual-contradiction-proof`
- standard benchmarks (MMMU-Pro, OCRBench, and the rest) — `elysian run-benchmark`
- the fifteen-check proof suite as a whole — `elysian proof-suite`

Each needs a CUDA machine and a model download. They are marked DEFERRED in
`CHECKLIST.md`, and a run that has not happened is not allowed to look like a
result: `elysian proof-suite` writes what it observed, and the checks that
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

`scripts/install.sh` is the developer setup with every local model. The memory itself needs none:
`pip install ./backend` installs the store, search, API, CLI and the backend MCP talks to, without
torch; `pip install "./backend[models]"` adds the local embedding, CLIP, speech and training stack.

Windows: the same names as `.ps1`. There is also a container image
(`docker build -t elysian .`), and CI runs the whole suite on Linux.

```bash
elysian ingest ~/some/package --cartridge-name project
elysian search "where did we put the archive key" --as-holder wife
elysian remember "the archive key is in the second drawer" --holder wife --scenario home
elysian who-knows "archive key"
elysian ask "where is the archive key" --as-holder husband
elysian card
elysian mounts && elysian mount project && elysian unmount
elysian backup ./backup && elysian doctor
bash scripts/mcp_write_smoke.sh        # two processes, one store, one SQLite
```

The dashboard is served by the API itself once `ELYSIAN_UI_DIR` points at
`frontend/dist`. `scripts/ui_smoke.sh` drives it in a real browser against a
fresh store and fails if any of it stops working. The CLI does everything the
console does, so nothing requires a browser.

## Retrieval

Three legs, fused by rank. The words leg always runs; speech is words, so a
transcript ranks in the same page as everything else. The dense leg runs only
when `ELYSIAN_DENSE_EMBEDDINGS_ENABLED=1` and an embedding model is configured.
Over every answerable query, at ten atoms it moves recall from 0.834 to 0.847,
and on a 30-atom page from 0.851 to 0.860, at several times the latency
(`bench/reports/LEGS.md` holds the timings and the load they were taken under).
It buys the memory questions (multi-session 0.857 → 0.920, preference 0.800 →
0.960) and costs the picture ones (image 0.781 → 0.773), which is why it is
opt-in rather than the default. The picture leg runs only
when the words page comes back thin and `ELYSIAN_CLIP_MODEL_DIR` is set.
A picture is searched by its words: with `ELYSIAN_VLM_BASE_URL` set, ingest asks the served
vision model to describe it (up to 512 tokens), printed text first;
`elysian describe-pictures` backfills a store written without one. With
`ELYSIAN_RERANK_BASE_URL` set, the served model judges each atom of the returned page
yes or no and the page is reordered by that judgement; the page keeps the same
memories, and a failed judge fails the search. Off by default.
Vectors live in the database beside the atoms, written in the same transaction
as the memory itself, so a memory is findable the moment it is stored and there
is no index to rebuild.

## MCP server for coding agents

`elysian-mcp/` is a Go MCP server. One command builds a native binary and
registers it with Codex and Claude Code. Reads mirror the store; writes go
through the API, so the write rules live in one place. When the API is down, the
MCP server starts `elysian serve` for the same home, waits for it to answer, and
leaves it running for the next client; its log is `~/.elysian/logs/api.log`.
`elysian init` makes the store and an operator token in `~/.elysian/auth_token`
(owner-only, never printed) that the API and the MCP server both read when
`ELYSIAN_AUTH_TOKEN` is unset. A read with no operator token sees only memories
nobody owns and memories marked for everyone; `elysian_card` answers "can this store answer my kind of question"
before anything sensitive is sent, and it carries no memory text.

```bash
bash ./elysian-mcp/install.sh --client both
```

See `elysian-mcp/README.md` for the full tool list.

## Data layout

One person keeps one store, in `~/.elysian/` unless `ELYSIAN_HOME` names another home. A
store left in a project directory from the old per-project layout stops the process with the
command that keeps it, instead of an empty store opening beside it.

```text
~/.elysian/
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
elysian-mcp/ Go: the MCP server
```

`CHECKLIST.md` is the ordered work list with the acceptance line for every item;
`Gaps.md` is the audit this work started from.

## License

MIT. Copyright © 2026 雷电芽衣 <yang@zacharyzhang.com>. See `LICENSE`.

Dependencies keep their own licenses. The PDF reader, PyMuPDF, is AGPL-3.0 or
an Artifex commercial license; whoever distributes or serves Elysian with it
installed takes on PyMuPDF's terms for that component.
