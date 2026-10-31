# Elysian（往世乐土）MCP

Elysian MCP exposes a local Context Cartridge memory store as a stdio Model Context Protocol server for coding agents such as Codex and Claude Code.

The server is local-first. Reads open `<elysian-home>/data/elysian.sqlite` read-only; writes go through the Elysian API, which owns the memory rules. When the API at `ELYSIAN_API` (default `http://127.0.0.1:8765`) does not answer, `server` starts `elysian serve` for the same home in its own session, waits up to 90 s for `/api/status`, and logs to `<elysian-home>/logs/api.log`; a remote `ELYSIAN_API` is never started. The operator token is `ELYSIAN_AUTH_TOKEN`, else `<elysian-home>/auth_token`, which `elysian init` writes.

The home follows the backend's rule: `--elysian-home`, else `ELYSIAN_HOME`, else `~/.elysian`. A per-project store left in the working directory stops the server with the command that keeps it.

## One-command setup

The repository's `install.sh` (Linux, macOS) and `install.ps1` (Windows) install everything; see
the top-level README. They download the checksum-verified binary of the newest `mcp-*` release into
`<elysian-home>/bin`, place the `elysian` CLI beside it (a link; a copy on Windows), and run `elysian-mcp setup`.

`setup` registers the server user-wide with every installed coding agent and skips the rest:
Codex (`codex mcp add`), Claude Code (`claude mcp remove` then `claude mcp add-json --scope user`),
Gemini CLI (`gemini mcp add --scope user`), OpenCode (`opencode mcp add`, 1.17 or newer), VS Code
(`code --add-mcp`; skipped under WSL, where `code` is the Windows editor) and Cursor (it edits
`~/.cursor/mcp.json` and keeps every other entry; a file that is not JSON stops setup untouched).
A re-run replaces the entry. `--client <name>` registers one and fails if it is missing.
`ELYSIAN_HOME` is written into the entry only when it was set or `--elysian-home` was given, and then
as the resolved absolute path. The JSON it prints ends with `any_other_client`, an `mcpServers` entry
for any other MCP client.

## Manual run

Against `~/.elysian`:

```bash
go run ./cmd/elysian-mcp server
```

Or point at another store:

```bash
go run ./cmd/elysian-mcp server --elysian-home /path/to/.elysian
```

## Tools

`elysian_status` returns atom, source, cartridge, token, and cache-layer counts.

`list_cartridges` lists local Context Cartridges with manifest JSON and Memory DNA.

`get_cartridge` reads one cartridge plus artifact metadata, memory capsule index, and asset report.

`search_atoms` queries the local SQLite FTS index and returns ranked Evidence Atoms.

`fetch_atom` reads one Evidence Atom by exact id.

`compile_context` compiles a question into a local evidence pack with the same profile names used by the app (`live_demo`, `extreme_context`, `library_100m`, `research_theater`).

`list_proof_suites` lists PRD proof suites under `<elysian-home>/data/eval_proofs`.

`list_hashhop_proofs` aggregates HashHop and Visual HashHop long-context addressing proofs by kind, hop count, and token budget, with pass counts and example proofs. Proofs are deduplicated by content-derived id.

`get_proof_suite` reads one PRD proof suite by id, including all checks and a summary of its HashHop proofs.

## Resources

`elysian://project/prd`, `elysian://project/readme`, and `elysian://project/mcp-research` expose `PRD.md`, the project README, and these research notes when those files are present next to the store.

## Releases

Pushing a `mcp-v*` tag runs `.github/workflows/mcp-release.yml`, which cross-compiles
the pure-Go server (CGO disabled) for Linux, macOS, and Windows on amd64 and arm64,
then publishes the archives with a `SHA256SUMS` manifest to a GitHub Release on
`ELY-Open-Source/Elysian`. The installers consume those assets.

## Security posture

The server opens SQLite read-only with `mode=ro` and `PRAGMA query_only(1)`, and uses `busy_timeout` so reads tolerate concurrent writes by the Elysian app. Tools expose structured outputs and return tool-level errors for invalid inputs so agents self-correct through normal tool calls. Proof ids are validated as single path elements before any filesystem read. The server uses stdio transport for local clients and takes credentials only from the local environment.
