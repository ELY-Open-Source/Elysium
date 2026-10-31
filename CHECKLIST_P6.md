# Phase 6: memory works by itself in every agent

One install and every coding agent recalls and saves memory with no toggle, no trust click and no
model choosing to call a tool. Each item lands through the codex reviewer (AGENTS.md) before `[x]`.

- [ ] p6-1 MCP tools carry honest hints (read-only, non-destructive, destructive), so clients that approve
      by hint (Codex `auto`, Droid risk levels) run them unprompted; only `forget_memory` destroys.
- [ ] p6-2 `elysian-mcp hook --client <name> <event>`: recall into context at session start and on each
      prompt, save the prompt (secrets masked, commands, replies and short questions skipped), one dialect
      per client payload, a per-client failure exit that never blocks a turn, failures in `logs/hook.log`.
- [ ] p6-3 setup wires Claude Code, Codex (hook trust pinned to our own hashes), Droid, Qwen Code, Gemini CLI.
- [ ] p6-4 setup wires Kiro, Antigravity, Kimi Code, Copilot CLI and VS Code (shared `~/.copilot`), Cursor.
- [ ] p6-5 setup wires Grok Build and Kigi (capture hooks plus a recall instruction: neither injects
      context on a prompt) and OpenCode (one plugin for V1 and V2).
- [ ] p6-6 installers, README and AGENTS say what runs where and what each client still gates
      (folder trust in Claude Code, Droid, Gemini, Grok, Kiro); release mcp-v0.3.0.
