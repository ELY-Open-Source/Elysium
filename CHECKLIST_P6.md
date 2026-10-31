# Phase 6: memory works by itself in every agent

One install and every coding agent recalls and saves memory with no toggle, no trust click and no
model choosing to call a tool. Each item lands through the codex reviewer (AGENTS.md) before `[x]`.

- [x] p6-1 MCP tools carry honest hints (read-only, non-destructive, destructive), so clients that approve
      by hint (Codex `auto`, Droid risk levels) run them unprompted; only `forget_memory` destroys.
- [x] p6-2 `elysian-mcp hook --client <name> <event>`: recall into context at session start and on each
      prompt, save the prompt (secrets masked, commands, replies and short questions skipped), one dialect
      per client payload, a per-client failure exit that never blocks a turn, failures in `logs/hook.log`.
      Three rounds used; the round-3 findings (kernel-lock claim, escaped quotes) were fixed in 5374594
      and verified in p6-3's review, whose D8 (lock wait within the prompt budget) was fixed and re-checked.
- [x] p6-3 setup wires every hook client but OpenCode: Claude Code, Codex (its server written with
      `default_tools_approval_mode = "approve"`, hook trust pinned to our own hashes), Droid, Qwen Code,
      Gemini CLI, Kiro, Antigravity, Kimi Code, Copilot CLI and VS Code (shared `~/.copilot`), Cursor,
      Grok Build and Kigi (capture hooks plus a recall instruction: neither injects context on a prompt).
      Three rounds used; the round-3 findings (trust position, multi-line strings) were verified in p6-4's PASS.
- [x] p6-4 OpenCode: one plugin for V1 and V2, proven against both installed versions.
- [x] p6-5 installers, README and AGENTS say what runs where and what each client still gates
      (folder trust in Claude Code, Droid, Gemini, Grok, Kiro); release mcp-v0.3.0.
