# Elysian（往世乐土）MCP

Elysian MCP exposes a local Context Cartridge memory store as a stdio Model Context Protocol server for coding agents such as Codex and Claude Code.

The server is local-first. Reads open `<elysian-home>/data/elysian.sqlite` read-only; writes go through the Elysian API, which owns the memory rules. When the API at `ELYSIAN_API` (default `http://127.0.0.1:8765`) does not answer, `server` starts `elysian serve` for the same home in its own session, waits up to 90 s for `/api/status`, and logs to `<elysian-home>/logs/api.log`; a remote `ELYSIAN_API` is never started. The operator token is `ELYSIAN_AUTH_TOKEN`, else `<elysian-home>/auth_token`, which `elysian init` writes.

The home follows the backend's rule: `--elysian-home`, else `ELYSIAN_HOME`, else `~/.elysian`. A per-project store left in the working directory stops the server with the command that keeps it.

## One-command setup

The repository's `install.sh` (Linux, macOS) and `install.ps1` (Windows) install everything; see
the top-level README. They download the checksum-verified binary of the newest `mcp-*` release into
`<elysian-home>/bin`, place the `elysian` CLI beside it (a link; a copy on Windows), and run `elysian-mcp setup`.

`setup` wires every installed coding agent so memory works by itself, and skips the rest. For each it
registers the server user-wide, turns off the prompt before Elysian's tools run, and adds hooks that run
`elysian-mcp hook --client <name> <event>`: at session start it adds the project's memories to the
agent's context, and on each prompt it recalls what matches, then saves the prompt (secrets masked;
commands, one-word replies and short questions skipped). A hook that fails never blocks the turn; it
writes the reason to stderr and `<elysian-home>/logs/hook.log`.

| Client | Server and approval | Hooks |
|---|---|---|
| Claude Code (≥2.1.139) | `claude mcp add-json --scope user`; `mcp__elysian__*` allowed in `~/.claude/settings.json` | SessionStart, UserPromptSubmit (exec form) |
| Codex | `[mcp_servers.elysian]` with `default_tools_approval_mode = "approve"` in `~/.codex/config.toml` | SessionStart, UserPromptSubmit in `hooks.json`, trusted by pinning their own hashes |
| Factory Droid | `~/.factory/mcp.json` | SessionStart, UserPromptSubmit, and a PreToolUse hook that approves `mcp__elysian__*` |
| Qwen Code | `~/.qwen/settings.json`, `trust: true` | SessionStart, UserPromptSubmit |
| Gemini CLI | `gemini mcp add --scope user --trust` | SessionStart, BeforeAgent |
| Kiro CLI | `~/.kiro/settings/mcp.json`, `autoApprove: ["*"]`; an allow rule in `permissions.yaml` | global V3 hooks in `~/.kiro/hooks/elysian.json` |
| Antigravity (`agy`) | `~/.gemini/config/mcp_config.json`; `mcp(elysian/*)` allowed | SessionStart, PreInvocation (once per prompt) |
| Kimi Code (2.x) | `~/.kimi-code/mcp.json`; an allow rule in `config.toml` | UserPromptSubmit, which also opens each session |
| Copilot CLI and VS Code | `~/.copilot/mcp-config.json` (VS Code's Copilot harness reads it; `code --add-mcp` too) | sessionStart, userPromptSubmitted, a permissionRequest hook that approves only Elysian's tools |
| Cursor | `~/.cursor/mcp.json`; `Mcp(elysian:*)` in `cli-config.json` when the CLI is there | sessionStart, beforeSubmitPrompt |
| OpenCode (1.x and 2.x) | `~/.config/opencode/opencode.json` | a plugin, `plugins/elysian.js` |
| Grok Build, Kigi | `[mcp_servers.elysian]` and `MCPTool(elysian__*)` in `config.toml` | a prompt hook that saves; their hooks cannot add context, so a rules file tells the model to recall |

What a client still asks for, setup does not decide for the user: Claude Code, Droid, Gemini CLI,
Grok and Kiro hold hooks (and some, the server) until a folder is trusted once. A file setup cannot
read as its format, or a TOML table it would have to define twice, stops that client untouched and is
named. A re-run replaces only Elysian's own entries. `--client <name>` wires one and fails if it is
missing. `ELYSIAN_HOME` is written into entries and hooks only when it was set or `--elysian-home`
was given. The JSON it prints ends with `any_other_client`, an `mcpServers` entry for any other client.

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

`elysian://project/prd`, `elysian://project/readme`, and `elysian://project/mcp-research` expose `PRD.md`, `README.md` and `elysian-mcp/docs/RESEARCH.md` from the project root: the directory the server was started in, or `--project-root`. The store's location plays no part. A file that is missing there is not listed.

## Releases

Pushing a `mcp-v*` tag runs `.github/workflows/mcp-release.yml`, which cross-compiles
the pure-Go server (CGO disabled) for Linux, macOS, and Windows on amd64 and arm64,
then publishes the archives with a `SHA256SUMS` manifest to a GitHub Release on
`ELY-Open-Source/Elysian`. The installers consume those assets, and the workflow's last job runs the
published one-line command on a bare Debian (`scripts/install_acceptance.sh`) against the release it made.

## Security posture

The server opens SQLite read-only with `mode=ro` and `PRAGMA query_only(1)`, and uses `busy_timeout` so reads tolerate concurrent writes by the Elysian app. Tools expose structured outputs and return tool-level errors for invalid inputs so agents self-correct through normal tool calls. Proof ids are validated as single path elements before any filesystem read. The server uses stdio transport for local clients and takes credentials only from the local environment.
