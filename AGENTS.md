# Agent notes for this repository

The project is **Elysian** (往世乐土), renamed from Ely-Eye, then from Elysium on 2026-10-30: the package is `elysian`, the CLI
`elysian`, the Go server `elysian-mcp`, variables `ELYSIAN_*`, the store `~/.elysian/data/elysian.sqlite`
(`ELYSIAN_HOME` names another home; backend and Go share the rule and refuse a per-project store left in the working directory).
Any old name stops the process (`config.refuse_old_names`, `elysian-mcp/internal/config`), because an
ignored `ELY_EYE_AUTH_TOKEN` or `ELYSIUM_AUTH_TOKEN` would start a server with no token. The repository is
`github.com/ELY-Open-Source/Elysian` and the Go module is `github.com/ELY-Open-Source/Elysian/elysian-mcp`.
The bench data root stays `~/ely_eye_bench_data` because the frozen stores record 50,155 source paths
under it. Frozen reports keep the arm names they were measured under (`elysium`); the harness reads them as Elysian.

Read `CHECKLIST.md` (phases 0–3) and `CHECKLIST_P4.md` (phase 4) for the ordered work list and `Gaps.md` for the audit the
work started from. Measured results live in `bench/reports/`. If a sentence in
this repository states a capability, there must be a command that demonstrates
it — otherwise the sentence belongs in the "not measured" section.

## Verify before you claim

Run the gates, and compare against the recorded baseline rather than "it built":

```bash
pytest -q                                       # both launch styles must work
ruff check backend/src/elysian backend/tests bench
.venv/bin/python -m bench.filesize_check         # fails on any tracked file > 500 lines
.venv/bin/python -m bench.audit --product        # the harness must not justify the product
.venv/bin/python -m mypy backend/src/elysian backend/tests   # cold cache; baseline is 17 errors in 5 files
./node_modules/.bin/pyright <the files you touched>          # must be 0 errors on touched files
cd elysian-mcp && go build ./... && go vet ./... && go test ./... && gofmt -l .
cd frontend && npm run build && npx eslint src --max-warnings 0
bash scripts/mcp_write_smoke.sh                  # two processes, one store
bash scripts/mcp_autostart_smoke.sh              # the MCP server starts the API itself
bash scripts/install_acceptance.sh --source      # one command on a bare Debian, then a client round trip
```

mypy carries a pre-existing error baseline. A change is clean when the count and
the file set match the recorded baseline; measure the baseline in a worktree of
the commit you branched from, do not assume it.

## Rules this repo enforces

- One writer per fact. Memory writes go through `MemoryService`; the Go MCP
  server forwards over HTTP instead of touching SQLite, so the rules cannot
  drift into two dialects.
- Fail fast and name the thing. `nothing to forget: no atom or source was given`,
  `database schema is version 99, this build understands 11`. A silent default
  that hides a caller's mistake is a defect, not a convenience.
- A file over 500 lines gets split before it gets commented.
- No dead code, no `v1`/`v2`/`v3` shadows of a thing that no longer exists.
- A `#` comment is one line. A docstring is a contract and may be longer.
- Absence is a state. `v_atoms_current` hides a closed, lapsed, or not-yet-valid
  memory; it does not delete it, and `atom_count()` still counts it.

## Measurement rules

- A number that moves with machine load is quoted as a range across runs, or it
  points at the report that holds it. Never quote a single load-dependent value
  as if it were stable.
- A report's commit stamp must name the commit that carries the harness that
  produced it. That is why a harness change and its report land as two commits: a
  report cannot stamp its own commit.
- Every recall number sits next to its chance floor and, where one exists, an
  external counterpart. `bench/reports/BASELINE_EXTERNAL.md` is the counterpart;
  the chance row is printed in the same table.
- One sample is not a benchmark. `next(iter(stream))` with `streaming=True` was
  how the old proof suite "scored" MMMU-Pro and OCRBench.
- A probe sample drawn by file order can silently drop a whole modality.
  `bench/query_set.py:scale_probes` is modality-stratified for that reason, and a
  test pins that every modality appears.
- A harness works on a copy of the frozen store (`bench/scratch.py:copy_store`).
  Never migrate `bench/runs/baseline/data/elysian.sqlite` in place.
- When two correct engines disagree, suspect the metric before the engine:
  byte-identical atoms produce tied scores, so id-level recall can read 0.83 for
  no real reason. `bench/reports/QUANT.md` scores a hit as "any returned atom
  whose true cosine is at least the K-th best".

## Environment traps already paid for

- pi-lens runs pyright with **0 config files**, so its `Import could not be
  resolved` findings for `pydantic`, `fastapi`, `torch`, `sqlite_vec` are an
  environment artifact. `./node_modules/.bin/pyright` reads `pyrightconfig.json`
  and is the one that counts.
- pi-lens auto-runs a `ruff format`-style formatter on files you touch. This
  repository is not ruff-format clean and its gate is `ruff check`, so revert
  that drift (`git checkout --`) before committing.
- Run `ruff check --fix` on explicit paths, never on the package: it will
  reformat a dozen unrelated files and you will commit them by accident.
- `bench/tests` import `bench.*`; the root `pyproject.toml` supplies
  `pythonpath = ["."]`, which is why bare `pytest` works.
- `import fitz` prints a deprecation warning to **stdout**, which corrupts every
  CLI JSON answer. Import it as `import pymupdf as fitz`.
- SQLite statements must be literals at the call site: the repo's semgrep rule
  rejects `connection.execute(variable, …)` even when the variable is a module
  constant. Where a rule must be copied, a test compares the copies
  (`backend/tests/test_visibility_rule.py`).

## Review protocol

Every task lands through an independent reviewer running in a `herdr` pane
against the commit, not against a description of it. The reviewer is
`codex --yolo -m gpt-6.1-sol -c model_reasoning_effort=xhigh -c service_tier=fast`,
at most 3 rounds per item. Findings are numbered
`D1…Dn`; fix the mechanism, not the wording, and re-measure. A checklist item is
not `[x]` before the reviewer returns PASS. Read the reviewer's verdict from its
session JSONL (the last assistant text block), not from a pane scroll-back that
may show an older round.

## Local install contract

`elysian init` makes `~/.elysian` and an owner-only operator token in `~/.elysian/auth_token`.
The backend (`config.read_token`) and Go (`config.resolveToken`) read it when `ELYSIAN_AUTH_TOKEN`
is unset; an empty file stops both. `elysian-mcp server` starts `elysian serve` when the local API
is down (`internal/backend`), using the `elysian` the installer links beside the binary before PATH;
`scripts/mcp_autostart_smoke.sh` proves it end to end. `install.sh` / `install.ps1` at the root are the only
installers: uv, `uv tool install` of the backend at the release tag, `elysian init`, the release binary, `elysian-mcp setup`.

## Public site

`site/` is the public site: pnpm, Vite, three.js and Lenis, an assets-only Cloudflare Worker
`elysian-site` on `elysian.elydora.com` (`site/wrangler.jsonc`). Scroll is time: every frame is drawn
from one value, so scrolling back rewinds. Its numbers come only from `README.md` and `bench/reports/`.
Gate: `cd site && pnpm build && node scripts/check.mjs --out <dir>` with `pnpm preview` running.

## Cross-language contract

`backend/src/elysian/schemas.py` is the source of truth. `elysian-mcp/internal/domain/types.go`
and `frontend/src/types.ts` mirror it; when a field changes there, it changes in
all three, and the smoke script is what proves the Go path agrees.
