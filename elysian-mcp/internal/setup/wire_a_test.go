//go:build !windows

package setup

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

var testServer = entry{Name: "elysian", Binary: "/opt/elysian-mcp", Env: map[string]string{}}

func readJSON(t *testing.T, path string) map[string]any {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	document := map[string]any{}
	if err := json.Unmarshal(data, &document); err != nil {
		t.Fatalf("%s: %v", path, err)
	}
	return document
}

func groups(t *testing.T, document map[string]any, event string) []any {
	t.Helper()
	hooks, _ := document["hooks"].(map[string]any)
	list, _ := hooks[event].([]any)
	return list
}

func TestClaudeGetsExecFormHooksAndAnApprovalAndARerunAddsNothing(t *testing.T) {
	home := isolate(t)
	bin := t.TempDir()
	fake(t, bin, "claude", false)
	path := filepath.Join(home, ".claude", "settings.json")
	os.MkdirAll(filepath.Dir(path), 0o700)
	os.WriteFile(path, []byte(`{"hooks":{"UserPromptSubmit":[{"hooks":[{"type":"command","command":"mine"}]}]},"theme":"dark"}`), 0o600)
	for range 2 {
		if _, err := wireClaude(context.Background(), filepath.Join(bin, "claude"), testServer); err != nil {
			t.Fatal(err)
		}
	}
	document := readJSON(t, path)
	allow := document["permissions"].(map[string]any)["allow"].([]any)
	if len(allow) != 1 || allow[0] != "mcp__elysian__*" || document["theme"] != "dark" {
		t.Fatalf("got %+v", document)
	}
	prompt := groups(t, document, "UserPromptSubmit")
	if len(prompt) != 2 || !strings.Contains(mustJSON(prompt[0]), `"mine"`) {
		t.Fatalf("the user's hook must stay and ours appear once, got %s", mustJSON(prompt))
	}
	if want := `"args":["hook","--client","claude","prompt"],"command":"/opt/elysian-mcp"`; !strings.Contains(mustJSON(prompt[1]), want) {
		t.Fatalf("got %s", mustJSON(prompt[1]))
	}
	if start := groups(t, document, "SessionStart"); len(start) != 1 || !strings.Contains(mustJSON(start), `"matcher":"startup|resume|clear|compact"`) {
		t.Fatalf("got %s", mustJSON(start))
	}
}

func TestAnOldClaudeCodeIsNamedNotWired(t *testing.T) {
	isolate(t)
	bin := t.TempDir()
	os.WriteFile(filepath.Join(bin, "claude"), []byte("#!/bin/sh\necho '2.1.100 (Claude Code)'\n"), 0o755)
	if _, err := wireClaude(context.Background(), filepath.Join(bin, "claude"), testServer); err == nil || !strings.Contains(err.Error(), "need 2.1.139 or newer") {
		t.Fatalf("got %v", err)
	}
}

func TestCodexHooksArePinnedTrustedOnceAndAUserTrustIsLeftAlone(t *testing.T) {
	home := isolate(t)
	dir := filepath.Join(home, ".codex")
	os.MkdirAll(dir, 0o700)
	os.WriteFile(filepath.Join(dir, "hooks.json"), []byte(`{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"herdr session","timeout":10}]}]}}`), 0o600)
	os.WriteFile(filepath.Join(dir, "config.toml"), []byte("model = \"x\"\n"), 0o600)
	for range 2 {
		if _, err := wireCodex(context.Background(), "", testServer); err != nil {
			t.Fatal(err)
		}
	}
	config, _ := os.ReadFile(filepath.Join(dir, "config.toml"))
	text := string(config)
	hooksPath := filepath.Join(dir, "hooks.json")
	command := "/opt/elysian-mcp hook --client codex session-start"
	hash, _ := codexHookHash("session_start", "^(startup|resume|clear|compact)$", command, 30)
	if strings.Count(text, ">>> elysian") != 1 || !strings.HasPrefix(text, "model = \"x\"") ||
		!strings.Contains(text, `[hooks.state."`+hooksPath+`:session_start:1:0"]`+"\ntrusted_hash = \""+hash+"\"") ||
		!strings.Contains(text, `:user_prompt_submit:0:0"]`) {
		t.Fatalf("got %s", text)
	}
	if start := groups(t, readJSON(t, hooksPath), "SessionStart"); len(start) != 2 || !strings.Contains(mustJSON(start[0]), "herdr") {
		t.Fatalf("herdr's hook must stay first, got %s", mustJSON(start))
	}
	user := "[hooks.state.\"" + hooksPath + ":user_prompt_submit:0:0\"]\ntrusted_hash = \"sha256:mine\"\n"
	os.WriteFile(filepath.Join(dir, "config.toml"), []byte(user), 0o600)
	if _, err := wireCodex(context.Background(), "", testServer); err != nil {
		t.Fatal(err)
	}
	config, _ = os.ReadFile(filepath.Join(dir, "config.toml"))
	if strings.Count(string(config), ":user_prompt_submit:0:0") != 1 {
		t.Fatalf("a trust the user gave must not be written twice, got %s", config)
	}
}

func TestDroidWritesMCPAndHooksAndKeepsSettingsHooksVisible(t *testing.T) {
	home := isolate(t)
	if _, err := registerDroid(context.Background(), "", testServer); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(home, ".factory")
	if spec := readJSON(t, filepath.Join(dir, "mcp.json"))["mcpServers"].(map[string]any)["elysian"].(map[string]any); spec["disabled"] != false || spec["command"] != "/opt/elysian-mcp" {
		t.Fatalf("got %+v", spec)
	}
	hooks := readJSON(t, filepath.Join(dir, "hooks.json"))
	if approve := mustJSON(hooks["PreToolUse"]); !strings.Contains(approve, `"matcher":"mcp__elysian__.*"`) || !strings.Contains(approve, "hook --client droid approve") {
		t.Fatalf("got %s", approve)
	}
	other := t.TempDir()
	t.Setenv("FACTORY_HOME", other)
	os.WriteFile(filepath.Join(other, "settings.json"), []byte(`{"hooks":{"Stop":[]}}`), 0o600)
	if _, err := registerDroid(context.Background(), "", testServer); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(other, "hooks.json")); err == nil {
		t.Fatal("a new hooks.json would hide the hooks in settings.json")
	}
	if prompt := groups(t, readJSON(t, filepath.Join(other, "settings.json")), "UserPromptSubmit"); len(prompt) != 1 {
		t.Fatalf("got %s", mustJSON(prompt))
	}
}

func TestQwenAndGeminiGetTrustedServersAndTheirHookNames(t *testing.T) {
	home := isolate(t)
	if _, err := registerQwen(context.Background(), "", testServer); err != nil {
		t.Fatal(err)
	}
	qwen := readJSON(t, filepath.Join(home, ".qwen", "settings.json"))
	if spec := qwen["mcpServers"].(map[string]any)["elysian"].(map[string]any); spec["trust"] != true {
		t.Fatalf("got %+v", spec)
	}
	if len(groups(t, qwen, "UserPromptSubmit")) != 1 || len(groups(t, qwen, "SessionStart")) != 1 {
		t.Fatalf("got %s", mustJSON(qwen))
	}
	if _, err := wireGemini(context.Background(), "", testServer); err != nil {
		t.Fatal(err)
	}
	gemini := readJSON(t, filepath.Join(home, ".gemini", "settings.json"))
	if before := mustJSON(groups(t, gemini, "BeforeAgent")); !strings.Contains(before, `"timeout":10000`) || !strings.Contains(before, "hook --client gemini prompt") {
		t.Fatalf("got %s", before)
	}
}

func TestShellCommandsQuoteForEachShell(t *testing.T) {
	cases := map[string]string{
		"sh":   `'/home/a b/elysian-mcp' hook`,
		"cmd":  `"/home/a b/elysian-mcp" hook`,
		"pwsh": `& '/home/a b/elysian-mcp' hook`,
	}
	for shell, want := range cases {
		if got := shellCommand("/home/a b/elysian-mcp", shell, "hook"); got != want {
			t.Fatalf("%s: got %s, want %s", shell, got, want)
		}
	}
	if _, err := plainCommand(`C:\Users\a b\elysian-mcp.exe`, "plain", "hook"); err == nil {
		t.Fatal("a path that needs quoting must be refused for an undocumented shell")
	}
}

func mustJSON(value any) string {
	var buffer strings.Builder
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	encoder.Encode(value)
	return strings.TrimRight(buffer.String(), "\n")
}
