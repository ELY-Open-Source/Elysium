package setup

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

func registerGemini(ctx context.Context, gemini string, server entry) (Action, error) {
	args := []string{"mcp", "add", "--scope", "user", "--trust"}
	for key, value := range server.Env {
		args = append(args, "--env", key+"="+value)
	}
	args = append(args, server.Name, server.Binary, "server")
	if output, err := exec.CommandContext(ctx, gemini, args...).CombinedOutput(); err != nil {
		return Action{}, errors.New("gemini mcp add failed: " + strings.TrimSpace(string(output)))
	}
	settings, err := wireGemini(ctx, gemini, server)
	if err != nil {
		return Action{}, err
	}
	return Action{Client: "gemini", Target: settings, Detail: "registered user-wide, trusted; session and prompt hooks", Command: commandLine(gemini, args)}, nil
}

func registerOpenCode(ctx context.Context, opencode string, server entry) (Action, error) {
	args := []string{"mcp", "add", server.Name}
	for key, value := range server.Env {
		args = append(args, "--env", key+"="+value)
	}
	args = append(args, "--", server.Binary, "server")
	if output, err := exec.CommandContext(ctx, opencode, args...).CombinedOutput(); err != nil {
		return Action{}, errors.New("opencode mcp add failed (it needs OpenCode 1.17 or newer): " + strings.TrimSpace(string(output)))
	}
	return Action{Client: "opencode", Target: "~/.config/opencode/opencode.json", Detail: "registered user-wide", Command: commandLine(opencode, args)}, nil
}

func registerVSCode(ctx context.Context, code string, server entry) (Action, error) {
	if wsl() {
		return Action{Client: "vscode", Detail: "skipped under WSL: `code` here is the Windows editor, which cannot run a Linux path; run the Windows installer"}, nil
	}
	payload, err := json.Marshal(map[string]any{"name": server.Name, "type": "stdio", "command": server.Binary, "args": []string{"server"}, "env": server.Env})
	if err != nil {
		return Action{}, err
	}
	args := []string{"--add-mcp", string(payload)}
	if output, err := exec.CommandContext(ctx, code, args...).CombinedOutput(); err != nil {
		return Action{}, errors.New("code --add-mcp failed: " + strings.TrimSpace(string(output)))
	}
	// VS Code's default Copilot harness reads ~/.copilot, where the hooks live.
	shared, err := registerCopilot(ctx, code, server)
	if err != nil {
		return Action{}, err
	}
	return Action{Client: "vscode", Target: "the VS Code user mcp.json and " + shared.Target, Detail: "registered user-wide; the Copilot harness gets session and prompt hooks", Command: commandLine(code, args)}, nil
}

// registerCursor edits ~/.cursor/mcp.json, the only user-wide surface Cursor documents; other entries are kept.
func registerCursor(_ context.Context, path string, server entry) (Action, error) {
	document := map[string]any{}
	data, err := os.ReadFile(path)
	if err == nil {
		if err := json.Unmarshal(data, &document); err != nil {
			return Action{}, errors.New(path + " is not JSON, so it was left untouched: " + err.Error())
		}
	} else if !errors.Is(err, os.ErrNotExist) {
		return Action{}, err
	}
	servers, ok := document["mcpServers"].(map[string]any)
	if document["mcpServers"] != nil && !ok {
		return Action{}, errors.New(path + " holds an mcpServers that is not an object, so it was left untouched")
	}
	if servers == nil {
		servers = map[string]any{}
	}
	servers[server.Name] = stdioEntry(server)
	document["mcpServers"] = servers
	encoded, err := json.MarshalIndent(document, "", "  ")
	if err != nil {
		return Action{}, err
	}
	temporary := path + ".elysian-tmp"
	if err := os.WriteFile(temporary, append(encoded, '\n'), 0o600); err != nil {
		return Action{}, err
	}
	if err := os.Rename(temporary, path); err != nil {
		return Action{}, err
	}
	hooks, err := wireCursor(path, server)
	if err != nil {
		return Action{}, err
	}
	return Action{Client: "cursor", Target: path + " and " + hooks, Detail: "registered user-wide; session and prompt hooks"}, nil
}

// cursorFile is Cursor's user config when Cursor has been run here.
func cursorFile() (string, error) {
	user, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	dir := filepath.Join(user, ".cursor")
	if info, err := os.Stat(dir); err != nil || !info.IsDir() {
		return "", errors.New(dir + " does not exist")
	}
	return filepath.Join(dir, "mcp.json"), nil
}

func stdioEntry(server entry) map[string]any {
	return map[string]any{"type": "stdio", "command": server.Binary, "args": []string{"server"}, "env": server.Env}
}

// generic is the mcpServers entry for any other MCP client.
func generic(server entry) map[string]any {
	return map[string]any{"mcpServers": map[string]any{server.Name: stdioEntry(server)}}
}

func wsl() bool {
	version, err := os.ReadFile("/proc/version")
	return err == nil && strings.Contains(strings.ToLower(string(version)), "microsoft")
}
