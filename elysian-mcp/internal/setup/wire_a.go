package setup

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"github.com/pelletier/go-toml/v2"
)

// wireClaude approves Elysian's tools and adds the session and prompt hooks to Claude Code's user
// settings. The hooks run in exec form (no shell), which Claude Code supports from 2.1.139.
func wireClaude(ctx context.Context, claude string, server entry) (string, error) {
	if err := atLeast(ctx, claude, "2.1.139"); err != nil {
		return "", err
	}
	dir, err := configHome("CLAUDE_CONFIG_DIR", ".claude")
	if err != nil {
		return "", err
	}
	path := filepath.Join(dir, "settings.json")
	handler := func(event string, timeout int) []any {
		return []any{map[string]any{"type": "command", "command": server.Binary, "args": hookArgs(server, "claude", event), "timeout": timeout}}
	}
	return path, editJSON(path, func(document map[string]any) error {
		permissions, err := object(document, "permissions", path)
		if err != nil {
			return err
		}
		if err := addString(permissions, "allow", "mcp__"+server.Name+"__*", path); err != nil {
			return err
		}
		hooks, err := object(document, "hooks", path)
		if err != nil {
			return err
		}
		if err := replaceGroups(hooks, "SessionStart", []any{map[string]any{"matcher": "startup|resume|clear|compact", "hooks": handler("session-start", 30)}}, path); err != nil {
			return err
		}
		return replaceGroups(hooks, "UserPromptSubmit", []any{map[string]any{"hooks": handler("prompt", 10)}}, path)
	})
}

// codexHooks are the hooks Codex runs; each is trusted by pinning its own hash.
var codexHooks = []struct{ event, snake, matcher, name string }{
	{"SessionStart", "session_start", "^(startup|resume|clear|compact)$", "session-start"},
	{"UserPromptSubmit", "user_prompt_submit", "", "prompt"},
}

// wireCodex adds the hooks to ~/.codex/hooks.json and trusts exactly those commands in config.toml,
// the record Codex writes itself when a user approves a hook in /hooks.
func wireCodex(_ context.Context, _ string, server entry) (string, error) {
	dir, err := configHome("CODEX_HOME", ".codex")
	if err != nil {
		return "", err
	}
	path := filepath.Join(dir, "hooks.json")
	shell := windowsShell("plain")
	commands := map[string]string{}
	for _, hook := range codexHooks {
		command, err := shellCommand(server.Binary, shell, hookArgs(server, "codex", hook.name)...)
		if err != nil {
			return "", err
		}
		commands[hook.event] = command
	}
	positions := map[string]int{}
	hooksFile, err := planJSON(path, func(document map[string]any) error {
		hooks, err := object(document, "hooks", path)
		if err != nil {
			return err
		}
		for _, hook := range codexHooks {
			group := map[string]any{"hooks": []any{map[string]any{"type": "command", "command": commands[hook.event], "timeout": 30}}}
			if hook.matcher != "" {
				group["matcher"] = hook.matcher
			}
			if err := replaceGroups(hooks, hook.event, []any{group}, path); err != nil {
				return err
			}
			positions[hook.event] = len(hooks[hook.event].([]any)) - 1
		}
		return nil
	})
	if err != nil {
		return "", err
	}
	absolute, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	configPath := filepath.Join(dir, "config.toml")
	text, _, err := readTOML(configPath)
	if err != nil {
		return "", err
	}
	// Our block is rewritten whole; what is left is the user's, checked and cleaned on its own.
	text = outsideBlock(text)
	var block strings.Builder
	block.WriteString("[mcp_servers." + server.Name + "]\ncommand = \"" + tomlEscape(server.Binary) + "\"\nargs = [\"server\"]\ndefault_tools_approval_mode = \"approve\"\n")
	if home := server.Env["ELYSIAN_HOME"]; home != "" {
		block.WriteString("\n[mcp_servers." + server.Name + ".env]\nELYSIAN_HOME = \"" + tomlEscape(home) + "\"\n")
	}
	// The server is written here whole, so an earlier definition goes, however its header is quoted.
	text = withoutTables(text, "mcp_servers", server.Name)
	for _, hook := range codexHooks {
		key := absolute + ":" + hook.snake + ":" + strconv.Itoa(positions[hook.event]) + ":0"
		// That position now holds our hook, so any trust recorded there is stale, whoever wrote it.
		text = withoutTables(text, "hooks", "state", key)
		hash, err := codexHookHash(hook.snake, hook.matcher, commands[hook.event], 30)
		if err != nil {
			return "", err
		}
		block.WriteString("\n[hooks.state.\"" + tomlEscape(key) + "\"]\ntrusted_hash = \"" + hash + "\"\n")
	}
	theirs := map[string]any{}
	if err := toml.Unmarshal([]byte(text), &theirs); err != nil {
		return "", errors.New(configPath + " is not valid TOML, so it was left untouched: " + err.Error())
	}
	if tomlHas(theirs, "mcp_servers", server.Name) {
		return "", errors.New(configPath + " defines mcp_servers." + server.Name + " inline, so it was left untouched; move it to its own [mcp_servers." + server.Name + "] table or remove it")
	}
	for _, hook := range codexHooks {
		if tomlHas(theirs, "hooks", "state", absolute+":"+hook.snake+":"+strconv.Itoa(positions[hook.event])+":0") {
			return "", errors.New(configPath + " records hook trust inline, so it was left untouched; remove hooks.state for " + path + " by hand")
		}
	}
	configFile, err := planTOMLBlock(configPath, text, block.String())
	if err != nil {
		return "", err
	}
	// Both files are checked before either is written, so a refusal leaves Codex as it was.
	if err := writeAtomic(path, hooksFile); err != nil {
		return "", err
	}
	return path + " and " + configPath, writeAtomic(configPath, configFile)
}

func tomlEscape(text string) string {
	return strings.ReplaceAll(strings.ReplaceAll(text, `\`, `\\`), `"`, `\"`)
}

// outsideBlock drops our own marked block, markers included, leaving only the user's text.
func outsideBlock(text string) string {
	begin := strings.Index(text, "# >>> elysian")
	end := strings.Index(text, "# <<< elysian")
	if begin < 0 || end < begin {
		return text
	}
	rest := text[end:]
	if newline := strings.Index(rest, "\n"); newline >= 0 {
		rest = rest[newline+1:]
	} else {
		rest = ""
	}
	return text[:begin] + rest
}

// registerDroid writes Factory Droid's MCP entry and hooks; the PreToolUse hook approves Elysian's
// tools, which Droid's default autonomy level would otherwise ask about.
func registerDroid(_ context.Context, _ string, server entry) (Action, error) {
	dir, err := userDir(".factory")
	if err != nil {
		return Action{}, err
	}
	mcpPath := filepath.Join(dir, "mcp.json")
	if err := editJSON(mcpPath, func(document map[string]any) error {
		servers, err := object(document, "mcpServers", mcpPath)
		if err != nil {
			return err
		}
		spec := stdioEntry(server)
		spec["disabled"] = false
		servers[server.Name] = spec
		return nil
	}); err != nil {
		return Action{}, err
	}
	commands, err := hookCommands(server, "droid", windowsShell("cmd"), "session-start", "prompt", "approve")
	if err != nil {
		return Action{}, err
	}
	group := func(event string, timeout int) map[string]any {
		return map[string]any{"hooks": []any{map[string]any{"type": "command", "command": commands[event], "timeout": timeout}}}
	}
	approve := group("approve", 5)
	approve["matcher"] = "mcp__" + server.Name + "__.*"
	// Droid reads settings.json hooks only when hooks.json is absent; a new hooks.json would hide them.
	hooksPath := filepath.Join(dir, "hooks.json")
	wrapped := false
	if _, err := os.Stat(hooksPath); errors.Is(err, os.ErrNotExist) && settingsHaveHooks(filepath.Join(dir, "settings.json")) {
		hooksPath, wrapped = filepath.Join(dir, "settings.json"), true
	}
	err = editJSON(hooksPath, func(document map[string]any) error {
		hooks := document
		if wrapped {
			var err error
			if hooks, err = object(document, "hooks", hooksPath); err != nil {
				return err
			}
		}
		for event, fresh := range map[string]map[string]any{"SessionStart": group("session-start", 30), "UserPromptSubmit": group("prompt", 10), "PreToolUse": approve} {
			if err := replaceGroups(hooks, event, []any{fresh}, hooksPath); err != nil {
				return err
			}
		}
		return nil
	})
	if err != nil {
		return Action{}, err
	}
	return Action{Client: "droid", Target: mcpPath + " and " + hooksPath, Detail: "registered user-wide; session and prompt hooks; Elysian's tools approved"}, nil
}

func settingsHaveHooks(path string) bool {
	found := false
	_ = editJSONRead(path, func(document map[string]any) { _, found = document["hooks"] })
	return found
}

// registerQwen writes Qwen Code's MCP entry, trusted so its tools run unprompted, and its hooks.
func registerQwen(_ context.Context, _ string, server entry) (Action, error) {
	dir, err := configHome("QWEN_HOME", ".qwen")
	if err != nil {
		return Action{}, err
	}
	path := filepath.Join(dir, "settings.json")
	shell := windowsShell("pwsh")
	commands, err := hookCommands(server, "qwen", shell, "session-start", "prompt")
	if err != nil {
		return Action{}, err
	}
	group := func(event, name string) map[string]any {
		handler := map[string]any{"type": "command", "name": name, "command": commands[event], "timeout": 10}
		if shell == "pwsh" {
			handler["shell"] = "powershell"
		}
		return map[string]any{"hooks": []any{handler}}
	}
	err = editJSON(path, func(document map[string]any) error {
		servers, err := object(document, "mcpServers", path)
		if err != nil {
			return err
		}
		spec := stdioEntry(server)
		delete(spec, "type")
		spec["trust"] = true
		servers[server.Name] = spec
		hooks, err := object(document, "hooks", path)
		if err != nil {
			return err
		}
		if err := replaceGroups(hooks, "SessionStart", []any{group("session-start", "elysian-session")}, path); err != nil {
			return err
		}
		return replaceGroups(hooks, "UserPromptSubmit", []any{group("prompt", "elysian-recall")}, path)
	})
	if err != nil {
		return Action{}, err
	}
	return Action{Client: "qwen", Target: path, Detail: "registered user-wide, trusted; session and prompt hooks"}, nil
}

// wireGemini adds Gemini CLI's SessionStart and BeforeAgent hooks; Gemini times them in milliseconds.
func wireGemini(_ context.Context, _ string, server entry) (string, error) {
	// GEMINI_CLI_HOME stands for the home directory; Gemini keeps .gemini inside it.
	root, err := configHome("GEMINI_CLI_HOME", "")
	if err != nil {
		return "", err
	}
	path := filepath.Join(root, ".gemini", "settings.json")
	commands, err := hookCommands(server, "gemini", windowsShell("pwsh"), "session-start", "prompt")
	if err != nil {
		return "", err
	}
	group := func(event, name string, timeout int) map[string]any {
		return map[string]any{"matcher": "*", "hooks": []any{map[string]any{"type": "command", "name": name, "command": commands[event], "timeout": timeout}}}
	}
	return path, editJSON(path, func(document map[string]any) error {
		hooks, err := object(document, "hooks", path)
		if err != nil {
			return err
		}
		if err := replaceGroups(hooks, "SessionStart", []any{group("session-start", "elysian-session", 30000)}, path); err != nil {
			return err
		}
		return replaceGroups(hooks, "BeforeAgent", []any{group("prompt", "elysian-recall", 10000)}, path)
	})
}

var versionPattern = regexp.MustCompile(`(\d+)\.(\d+)\.(\d+)`)

// atLeast fails when the client's --version is older than minimum, naming both.
func atLeast(ctx context.Context, program, minimum string) error {
	output, err := exec.CommandContext(ctx, program, "--version").CombinedOutput()
	if err != nil {
		return errors.New(program + " --version failed: " + strings.TrimSpace(string(output)))
	}
	have := versionPattern.FindStringSubmatch(string(output))
	want := versionPattern.FindStringSubmatch(minimum)
	if have == nil {
		return errors.New(program + " --version printed no version: " + strings.TrimSpace(string(output)))
	}
	for i := 1; i <= 3; i++ {
		a, _ := strconv.Atoi(have[i])
		b, _ := strconv.Atoi(want[i])
		if a != b {
			if a < b {
				return errors.New(program + " is " + have[0] + "; Elysian's hooks need " + minimum + " or newer")
			}
			return nil
		}
	}
	return nil
}
