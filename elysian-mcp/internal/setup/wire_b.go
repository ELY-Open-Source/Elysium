package setup

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// registerKiro writes Kiro's MCP entry with every tool approved, a global V3 hook file that every agent
// runs, and the permission rule V3 needs before it stops asking.
func registerKiro(_ context.Context, _ string, server entry) (Action, error) {
	dir, err := configHome("KIRO_HOME", ".kiro")
	if err != nil {
		return Action{}, err
	}
	mcpPath := filepath.Join(dir, "settings", "mcp.json")
	if err := editJSON(mcpPath, func(document map[string]any) error {
		servers, err := object(document, "mcpServers", mcpPath)
		if err != nil {
			return err
		}
		spec := stdioEntry(server)
		delete(spec, "type")
		spec["disabled"] = false
		spec["autoApprove"] = []any{"*"}
		servers[server.Name] = spec
		return nil
	}); err != nil {
		return Action{}, err
	}
	shell := windowsShell("plain")
	var hooks []any
	for _, hook := range []struct{ name, trigger, event string }{{"elysian-session", "SessionStart", "session-start"}, {"elysian-recall", "UserPromptSubmit", "prompt"}} {
		command, err := plainCommand(server.Binary, shell, hookArgs(server, "kiro", hook.event)...)
		if err != nil {
			return Action{}, err
		}
		hooks = append(hooks, map[string]any{"name": hook.name, "trigger": hook.trigger, "timeout": 30, "action": map[string]any{"type": "command", "command": command}})
	}
	hookPath := filepath.Join(dir, "hooks", "elysian.json")
	if err := editJSON(hookPath, func(document map[string]any) error {
		document["version"], document["hooks"] = "v1", hooks
		return nil
	}); err != nil {
		return Action{}, err
	}
	detail := "registered user-wide, tools auto-approved; global session and prompt hooks"
	note, err := kiroPermission(filepath.Join(dir, "settings", "permissions.yaml"), server.Name)
	if err != nil {
		return Action{}, err
	}
	return Action{Client: "kiro", Target: mcpPath + ", " + hookPath, Detail: detail + note}, nil
}

// kiroPermission adds `capability: mcp, match: [name/*], effect: allow` to permissions.yaml when the
// file is absent or its last top-level key is the rules list; any other layout is left alone and named.
func kiroPermission(path, name string) (string, error) {
	rule := []string{"capability: mcp", `match: ["` + name + `/*"]`, "effect: allow"}
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return "", writeAtomic(path, []byte("rules:\n"+yamlItem(rule, "  ")))
	}
	if err != nil {
		return "", err
	}
	text := strings.TrimRight(string(data), "\n")
	if strings.Contains(text, `"`+name+`/*"`) {
		return "", nil
	}
	lines := strings.Split(text, "\n")
	rules, indent := -1, "  "
	for i, line := range lines {
		switch {
		case line == "rules:":
			rules = i
		case rules >= 0 && line != "" && !strings.HasPrefix(line, " ") && !strings.HasPrefix(line, "- ") && !strings.HasPrefix(line, "#"):
			rules = -1
		}
	}
	if rules >= 0 {
		for _, line := range lines[rules+1:] {
			if trimmed := strings.TrimLeft(line, " "); strings.HasPrefix(trimmed, "- ") {
				indent = line[:len(line)-len(trimmed)]
				break
			}
		}
	}
	if rules < 0 {
		return "; add this rule to " + path + " by hand, its layout is its own: " + strings.Join(rule, ", "), nil
	}
	return "", writeAtomic(path, []byte(text+"\n"+yamlItem(rule, indent)))
}

// yamlItem renders one list item whose first key follows "- " at indent.
func yamlItem(keys []string, indent string) string {
	var out strings.Builder
	for i, key := range keys {
		if i == 0 {
			out.WriteString(indent + "- " + key + "\n")
		} else {
			out.WriteString(indent + "  " + key + "\n")
		}
	}
	return out.String()
}

// registerAntigravity writes agy's MCP entry, the permission that stops it asking, and a named hook set.
func registerAntigravity(_ context.Context, _ string, server entry) (Action, error) {
	dir, err := userDir(".gemini")
	if err != nil {
		return Action{}, err
	}
	mcpPath := filepath.Join(dir, "config", "mcp_config.json")
	if err := editJSON(mcpPath, func(document map[string]any) error {
		servers, err := object(document, "mcpServers", mcpPath)
		if err != nil {
			return err
		}
		spec := stdioEntry(server)
		delete(spec, "type")
		servers[server.Name] = spec
		return nil
	}); err != nil {
		return Action{}, err
	}
	settings := filepath.Join(dir, "antigravity-cli", "settings.json")
	if err := editJSON(settings, func(document map[string]any) error {
		permissions, err := object(document, "permissions", settings)
		if err != nil {
			return err
		}
		return addString(permissions, "allow", "mcp("+server.Name+"/*)", settings)
	}); err != nil {
		return Action{}, err
	}
	shell := windowsShell("plain")
	handler := func(event string, timeout int) ([]any, error) {
		command, err := plainCommand(server.Binary, shell, hookArgs(server, "agy", event)...)
		return []any{map[string]any{"type": "command", "command": command, "timeout": timeout}}, err
	}
	start, err := handler("session-start", 30)
	if err != nil {
		return Action{}, err
	}
	prompt, _ := handler("prompt", 10)
	hookPath := filepath.Join(dir, "config", "hooks.json")
	if err := editJSON(hookPath, func(document map[string]any) error {
		document["elysian"] = map[string]any{"SessionStart": start, "PreInvocation": prompt}
		return nil
	}); err != nil {
		return Action{}, err
	}
	return Action{Client: "agy", Target: mcpPath + ", " + settings + ", " + hookPath, Detail: "registered user-wide, tools allowed; session and prompt hooks"}, nil
}

// registerKimi writes Kimi Code's MCP entry, its allow rule and its prompt hook; Kimi's session hook
// cannot add context, so the first prompt of a session carries it. Legacy 1.x only gets the server.
func registerKimi(ctx context.Context, kimi string, server entry) (Action, error) {
	version, err := exec.CommandContext(ctx, kimi, "--version").CombinedOutput()
	if err != nil {
		return Action{}, errors.New("kimi --version failed: " + strings.TrimSpace(string(version)))
	}
	if match := versionPattern.FindStringSubmatch(string(version)); match != nil && match[1] == "1" {
		if len(server.Env) > 0 {
			return Action{Client: "kimi", Detail: "not registered: kimi-cli 1.x is archived and its `mcp add` cannot carry ELYSIAN_HOME; run `kimi migrate` to Kimi Code and set up again"}, nil
		}
		args := []string{"mcp", "add", server.Name, "--", server.Binary, "server"}
		if output, err := exec.CommandContext(ctx, kimi, args...).CombinedOutput(); err != nil {
			return Action{}, errors.New("kimi mcp add failed: " + strings.TrimSpace(string(output)))
		}
		return Action{Client: "kimi", Target: "~/.kimi/mcp.json", Detail: "registered; kimi-cli 1.x is archived and gets no hooks: run `kimi migrate` to Kimi Code and set up again", Command: commandLine(kimi, args)}, nil
	}
	dir, err := configHome("KIMI_CODE_HOME", ".kimi-code")
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
		delete(spec, "type")
		spec["startupTimeoutMs"] = 60000
		servers[server.Name] = spec
		return nil
	}); err != nil {
		return Action{}, err
	}
	configPath := filepath.Join(dir, "config.toml")
	text, _, err := readTOML(configPath)
	if err != nil {
		return Action{}, err
	}
	command := shellCommand(server.Binary, windowsShell("cmd"), hookArgs(server, "kimi", "prompt")...)
	hook := "[[hooks]]\nevent = \"UserPromptSubmit\"\ncommand = \"" + tomlEscape(command) + "\"\ntimeout = 10"
	rule := "[[permission.rules]]\ndecision = \"allow\"\npattern = \"mcp__" + server.Name + "__*\""
	detail := "registered user-wide; prompt hook (it opens each session too); Elysian's tools allowed"
	// The user's own layout decides what can be added: a rule list written inline cannot take [[...]].
	if err := writeTOMLBlock(configPath, text, rule+"\n\n"+hook); err != nil {
		if err := writeTOMLBlock(configPath, text, hook); err != nil {
			return Action{}, err
		}
		detail = "registered user-wide; prompt hook (it opens each session too); permission rules are written inline in " + configPath + ", so add mcp__" + server.Name + "__* to them by hand"
	}
	return Action{Client: "kimi", Target: mcpPath + " and " + configPath, Detail: detail}, nil
}

// registerCopilot writes the files Copilot CLI and VS Code's default Copilot harness share.
func registerCopilot(_ context.Context, _ string, server entry) (Action, error) {
	dir, err := configHome("COPILOT_HOME", ".copilot")
	if err != nil {
		return Action{}, err
	}
	mcpPath := filepath.Join(dir, "mcp-config.json")
	if err := editJSON(mcpPath, func(document map[string]any) error {
		servers, err := object(document, "mcpServers", mcpPath)
		if err != nil {
			return err
		}
		spec := stdioEntry(server)
		spec["tools"] = []any{"*"}
		servers[server.Name] = spec
		return nil
	}); err != nil {
		return Action{}, err
	}
	handler := func(event string, timeout int) []any {
		args := hookArgs(server, "copilot", event)
		return []any{map[string]any{"type": "command", "bash": shellCommand(server.Binary, "sh", args...), "powershell": shellCommand(server.Binary, "pwsh", args...), "timeoutSec": timeout}}
	}
	hookPath := filepath.Join(dir, "hooks", "elysian.json")
	if err := editJSON(hookPath, func(document map[string]any) error {
		document["version"] = 1
		document["hooks"] = map[string]any{"sessionStart": handler("session-start", 30), "userPromptSubmitted": handler("prompt", 10), "permissionRequest": handler("approve", 5)}
		return nil
	}); err != nil {
		return Action{}, err
	}
	return Action{Client: "copilot", Target: mcpPath + " and " + hookPath, Detail: "registered user-wide (Copilot CLI and VS Code's Copilot harness); session and prompt hooks; Elysian's tools approved"}, nil
}

// wireCursor adds Cursor's sessionStart and beforeSubmitPrompt hooks and, for its CLI, the allow rule.
func wireCursor(path string, server entry) (string, error) {
	dir := filepath.Dir(path)
	shell := windowsShell("pwsh")
	hookPath := filepath.Join(dir, "hooks.json")
	err := editJSON(hookPath, func(document map[string]any) error {
		if _, ok := document["version"]; !ok {
			document["version"] = 1
		}
		hooks, err := object(document, "hooks", hookPath)
		if err != nil {
			return err
		}
		for event, spec := range map[string]struct {
			name    string
			timeout int
		}{"sessionStart": {"session-start", 30}, "beforeSubmitPrompt": {"prompt", 10}} {
			list, ok := hooks[event].([]any)
			if hooks[event] != nil && !ok {
				return errors.New(hookPath + " holds hooks." + event + " that is not a list, so it was left untouched")
			}
			kept := []any{}
			for _, handler := range list {
				if !ours(handler) {
					kept = append(kept, handler)
				}
			}
			hooks[event] = append(kept, map[string]any{"command": shellCommand(server.Binary, shell, hookArgs(server, "cursor", spec.name)...), "timeout": spec.timeout})
		}
		return nil
	})
	if err != nil {
		return "", err
	}
	cli := filepath.Join(dir, "cli-config.json")
	if _, err := os.Stat(cli); err != nil {
		return hookPath, nil
	}
	return hookPath + " and " + cli, editJSON(cli, func(document map[string]any) error {
		permissions, err := object(document, "permissions", cli)
		if err != nil {
			return err
		}
		return addString(permissions, "allow", "Mcp("+server.Name+":*)", cli)
	})
}
