package setup

import (
	"context"
	_ "embed"
	"encoding/json"
	"path/filepath"
	"strings"
)

//go:embed opencode.js
var openCodePlugin string

// registerOpenCode writes the global config and plugin both OpenCode lines read: `opencode mcp add`
// cannot, since 2.x writes the current folder's project config and 1.x refuses --global.
func registerOpenCode(_ context.Context, _ string, server entry) (Action, error) {
	root, err := configHome("XDG_CONFIG_HOME", ".config")
	if err != nil {
		return Action{}, err
	}
	dir := filepath.Join(root, "opencode")
	// OpenCode merges config.json, opencode.json and opencode.jsonc, so a user's commented .jsonc stays untouched.
	path := filepath.Join(dir, "opencode.json")
	if err := editJSON(path, func(document map[string]any) error {
		servers, err := object(document, "mcp", path)
		if err != nil {
			return err
		}
		environment := map[string]any{}
		for key, value := range server.Env {
			environment[key] = value
		}
		servers[server.Name] = map[string]any{"type": "local", "command": []any{server.Binary, "server"}, "environment": environment, "enabled": true}
		return nil
	}); err != nil {
		return Action{}, err
	}
	binary, err := json.Marshal(server.Binary)
	if err != nil {
		return Action{}, err
	}
	home := []byte("null")
	if value := server.Env["ELYSIAN_HOME"]; value != "" {
		if home, err = json.Marshal(value); err != nil {
			return Action{}, err
		}
	}
	plugin := strings.NewReplacer("__ELYSIAN_BINARY__", string(binary), "__ELYSIAN_HOME__", string(home)).Replace(openCodePlugin)
	pluginPath := filepath.Join(dir, "plugins", "elysian.js")
	if err := writeAtomic(pluginPath, []byte(plugin)); err != nil {
		return Action{}, err
	}
	return Action{Client: "opencode", Target: path + " and " + pluginPath, Detail: "registered user-wide (OpenCode 1.x and 2.x); a plugin recalls at session start and on each prompt and saves the prompt"}, nil
}
