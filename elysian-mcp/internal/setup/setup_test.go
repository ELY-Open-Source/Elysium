//go:build !windows

package setup

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/config"
)

// fake writes a client CLI that logs its arguments and answers remove as the real one does.
func fake(t *testing.T, bin string, name string, removeExists bool) {
	t.Helper()
	remove := `echo "No MCP server named \"elysian\" in user scope"; exit 1`
	if removeExists {
		remove = `echo "Removed MCP server elysian"; exit 0`
	}
	script := "#!/bin/sh\nif [ \"$1\" = --version ]; then echo '2.1.314 (Claude Code)'; exit 0; fi\n" +
		"echo \"$@\" >> \"" + filepath.Join(bin, name+".log") + "\"\n" +
		"if [ \"$2\" = remove ]; then " + remove + "; fi\n"
	if err := os.WriteFile(filepath.Join(bin, name), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
}

// isolate points HOME and every client's config override at temporary places, so no test touches a real config.
func isolate(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	for _, key := range []string{"CLAUDE_CONFIG_DIR", "CODEX_HOME", "FACTORY_HOME", "QWEN_HOME", "GEMINI_CLI_HOME", "KIRO_HOME", "KIMI_CODE_HOME", "COPILOT_HOME", "GROK_HOME", "XDG_CONFIG_HOME"} {
		t.Setenv(key, "")
	}
	return home
}

func logged(t *testing.T, bin string, name string) string {
	t.Helper()
	data, err := os.ReadFile(filepath.Join(bin, name+".log"))
	if err != nil {
		return ""
	}
	return string(data)
}

func TestEveryInstalledClientIsRegisteredUserWideAndAMissingOneSkipped(t *testing.T) {
	bin := t.TempDir()
	fake(t, bin, "claude", false)
	t.Setenv("PATH", bin)
	isolate(t)
	result, err := Run(context.Background(), config.Config{Binary: "/opt/elysian-mcp"}, Options{})
	if err != nil {
		t.Fatal(err)
	}
	details := map[string]string{}
	for _, action := range result.Actions {
		details[action.Client] = action.Detail
	}
	for _, missing := range []string{"codex", "droid", "qwen", "cursor", "gemini", "opencode", "vscode"} {
		if details[missing] != "not installed; skipped" {
			t.Fatalf("%s must be skipped, got %+v", missing, result.Actions)
		}
	}
	if !strings.HasPrefix(details["claude"], "registered user-wide") {
		t.Fatalf("claude must be registered, got %+v", result.Actions)
	}
	calls := logged(t, bin, "claude")
	if !strings.Contains(calls, "mcp remove elysian --scope user") ||
		!strings.Contains(calls, `mcp add-json elysian {"args":["server"],"command":"/opt/elysian-mcp","env":{},"type":"stdio"} --scope user`) {
		t.Fatalf("claude must be registered user-wide with no pinned home, got %q", calls)
	}
}

func TestARerunReplacesTheEntryAndANamedHomeIsCarried(t *testing.T) {
	bin := t.TempDir()
	fake(t, bin, "claude", true)
	fake(t, bin, "codex", true)
	t.Setenv("PATH", bin)
	home := isolate(t)
	if _, err := Run(context.Background(), config.Config{Binary: "/opt/elysian-mcp"}, Options{Home: "/data/elysian"}); err != nil {
		t.Fatalf("a re-run must replace the entries, got %v", err)
	}
	codexConfig, _ := os.ReadFile(filepath.Join(home, ".codex", "config.toml"))
	if calls := logged(t, bin, "codex"); calls != "" ||
		!strings.Contains(string(codexConfig), "[mcp_servers.elysian]\ncommand = \"/opt/elysian-mcp\"\nargs = [\"server\"]\ndefault_tools_approval_mode = \"approve\"\n\n[mcp_servers.elysian.env]\nELYSIAN_HOME = \"/data/elysian\"") {
		t.Fatalf("codex must be written with its approval mode and the named home, got %q and %s", calls, codexConfig)
	}
	hooks, _ := os.ReadFile(filepath.Join(home, ".codex", "hooks.json"))
	if !strings.Contains(string(hooks), "hook --client codex --elysian-home /data/elysian prompt") {
		t.Fatalf("codex hooks must carry the named home, got %s", hooks)
	}
	if calls := logged(t, bin, "claude"); !strings.Contains(calls, `"env":{"ELYSIAN_HOME":"/data/elysian"}`) {
		t.Fatalf("claude must carry the named home, got %q", calls)
	}
}

func TestANamedClientThatIsMissingIsAnError(t *testing.T) {
	t.Setenv("PATH", t.TempDir())
	isolate(t)
	_, err := Run(context.Background(), config.Config{Binary: "/opt/elysian-mcp"}, Options{Client: "codex"})
	if err == nil || !strings.Contains(err.Error(), "codex is not installed here") {
		t.Fatalf("a named missing client must be an error, got %v", err)
	}
}

func TestGeminiOpenCodeAndVSCodeAreRegisteredThroughTheirCLIs(t *testing.T) {
	bin := t.TempDir()
	fake(t, bin, "gemini", false)
	fake(t, bin, "opencode", false)
	fake(t, bin, "code", false)
	t.Setenv("PATH", bin)
	home := isolate(t)
	result, err := Run(context.Background(), config.Config{Binary: "/opt/elysian-mcp"}, Options{Home: "/data/elysian"})
	if err != nil {
		t.Fatal(err)
	}
	if calls := logged(t, bin, "gemini"); !strings.Contains(calls, "mcp add --scope user --trust --env ELYSIAN_HOME=/data/elysian elysian /opt/elysian-mcp server") {
		t.Fatalf("gemini must be registered user-wide, got %q", calls)
	}
	openCode, _ := os.ReadFile(filepath.Join(home, ".config", "opencode", "opencode.json"))
	plugin, _ := os.ReadFile(filepath.Join(home, ".config", "opencode", "plugins", "elysian.js"))
	if !strings.Contains(string(openCode), `"command": [
        "/opt/elysian-mcp",
        "server"
      ]`) || !strings.Contains(string(plugin), `const BINARY = "/opt/elysian-mcp";`) || !strings.Contains(string(plugin), `const HOME = "/data/elysian";`) {
		t.Fatalf("opencode must get its global entry and plugin, got %s\n%.300s", openCode, plugin)
	}
	code := logged(t, bin, "code")
	if wsl() {
		if code != "" {
			t.Fatalf("under WSL the Windows editor must not be given a Linux path, got %q", code)
		}
	} else if !strings.Contains(code, `--add-mcp {"args":["server"],"command":"/opt/elysian-mcp","env":{"ELYSIAN_HOME":"/data/elysian"},"name":"elysian","type":"stdio"}`) {
		t.Fatalf("vscode must be registered, got %q", code)
	}
	other := result.AnyOtherClient["mcpServers"].(map[string]any)["elysian"].(map[string]any)
	if other["command"] != "/opt/elysian-mcp" || other["type"] != "stdio" {
		t.Fatalf("any other client must get a stdio entry, got %+v", result.AnyOtherClient)
	}
}

func TestCursorKeepsItsOtherServersAndABrokenFileIsLeftAlone(t *testing.T) {
	home := isolate(t)
	t.Setenv("PATH", t.TempDir())
	path := filepath.Join(home, ".cursor", "mcp.json")
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(`{"mcpServers":{"other":{"command":"x"}},"theme":"dark"}`), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Run(context.Background(), config.Config{Binary: "/opt/elysian-mcp"}, Options{Client: "cursor"}); err != nil {
		t.Fatal(err)
	}
	data, _ := os.ReadFile(path)
	if !strings.Contains(string(data), `"other"`) || !strings.Contains(string(data), `"theme": "dark"`) || !strings.Contains(string(data), `"command": "/opt/elysian-mcp"`) {
		t.Fatalf("cursor's file must keep what it had and gain elysian, got %s", data)
	}
	if err := os.WriteFile(path, []byte("{ // not json"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := Run(context.Background(), config.Config{Binary: "/opt/elysian-mcp"}, Options{Client: "cursor"}); err == nil || !strings.Contains(err.Error(), "is not JSON, so it was left untouched") {
		t.Fatalf("a broken cursor file must stop setup, got %v", err)
	}
	if data, _ := os.ReadFile(path); string(data) != "{ // not json" {
		t.Fatalf("a broken cursor file must be left as it was, got %s", data)
	}
}
