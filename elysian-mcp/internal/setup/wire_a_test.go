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
	other := filepath.Join(isolate(t), ".factory")
	os.MkdirAll(other, 0o700)
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
		if got, err := shellCommand("/home/a b/elysian-mcp", shell, "hook"); err != nil || got != want {
			t.Fatalf("%s: got %s %v, want %s", shell, got, err, want)
		}
	}
	if got, _ := shellCommand("/opt/elysian-mcp", "sh", `memory\store`); got != `/opt/elysian-mcp 'memory\store'` {
		t.Fatalf("a POSIX shell must not read a backslash as an escape, got %s", got)
	}
	if got, _ := shellCommand(`C:\Users\a\elysian-mcp.exe`, "pwsh", "hook"); got != `& C:\Users\a\elysian-mcp.exe hook` {
		t.Fatalf("a Windows path needs no quoting in PowerShell, got %s", got)
	}
	if _, err := shellCommand(`C:\%HOME%\elysian-mcp.exe`, "cmd", "hook"); err == nil {
		t.Fatal("cmd.exe expands %VARIABLES% inside quotes, so such a path must be refused")
	}
	if _, err := shellCommand(`C:\Users\a b\elysian-mcp.exe`, "plain", "hook"); err == nil {
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

func TestReviewOfP63(t *testing.T) {
	t.Run("D1 a user's handler sharing a group with ours survives a re-run", func(t *testing.T) {
		home := isolate(t)
		path := filepath.Join(home, ".qwen", "settings.json")
		os.MkdirAll(filepath.Dir(path), 0o700)
		os.WriteFile(path, []byte(`{"hooks":{"UserPromptSubmit":[{"hooks":[{"type":"command","command":"/opt/elysian-mcp hook --client qwen prompt"},{"type":"command","command":"python user_policy.py"}]}]}}`), 0o600)
		if _, err := registerQwen(context.Background(), "", testServer); err != nil {
			t.Fatal(err)
		}
		prompt := mustJSON(groups(t, readJSON(t, path), "UserPromptSubmit"))
		if !strings.Contains(prompt, "user_policy.py") || strings.Count(prompt, "elysian-mcp hook") != 1 {
			t.Fatalf("got %s", prompt)
		}
	})
	t.Run("D2 a home with a space is quoted in the hook command", func(t *testing.T) {
		home := isolate(t)
		server := entry{Name: "elysian", Binary: "/opt/elysian-mcp", Env: map[string]string{"ELYSIAN_HOME": "/data/memory store"}}
		if _, err := registerQwen(context.Background(), "", server); err != nil {
			t.Fatal(err)
		}
		if prompt := mustJSON(groups(t, readJSON(t, filepath.Join(home, ".qwen", "settings.json")), "UserPromptSubmit")); !strings.Contains(prompt, `--elysian-home '/data/memory store' prompt`) {
			t.Fatalf("got %s", prompt)
		}
		if _, err := shellCommand("/opt/elysian-mcp", "plain", "--elysian-home", "/data/memory store"); err == nil {
			t.Fatal("an argument that needs quoting must be refused for an undocumented shell")
		}
	})
	t.Run("D3 quoted table names and inline tables are read as TOML", func(t *testing.T) {
		home := isolate(t)
		grokConfig := filepath.Join(home, ".grok", "config.toml")
		os.MkdirAll(filepath.Dir(grokConfig), 0o700)
		os.WriteFile(grokConfig, []byte("[mcp_servers.\"elysian\"]\ncommand = \"x\"\n\n[\"permission\"]\nallow = []\n"), 0o600)
		action, err := registerGrok(context.Background(), "", testServer)
		data, _ := os.ReadFile(grokConfig)
		if err != nil || strings.Contains(string(data), "[mcp_servers.elysian]") || strings.Contains(string(data), "\n[permission]") || !strings.Contains(action.Detail, "by hand") {
			t.Fatalf("got %+v %v\n%s", action, err, data)
		}
		bin := t.TempDir()
		kimi := filepath.Join(bin, "kimi")
		os.WriteFile(kimi, []byte("#!/bin/sh\necho 'kimi-code 2.4.1'\n"), 0o755)
		kimiConfig := filepath.Join(home, ".kimi-code", "config.toml")
		os.MkdirAll(filepath.Dir(kimiConfig), 0o700)
		os.WriteFile(kimiConfig, []byte("permission = { rules = [] }\n"), 0o600)
		action, err = registerKimi(context.Background(), kimi, testServer)
		data, _ = os.ReadFile(kimiConfig)
		if _, _, parseErr := readTOML(kimiConfig); err != nil || parseErr != nil || strings.Contains(string(data), "[[permission.rules]]") || !strings.Contains(action.Detail, "by hand") {
			t.Fatalf("got %+v %v %v\n%s", action, err, parseErr, data)
		}
	})
	t.Run("D4 a stale trust at our hook's position is replaced", func(t *testing.T) {
		home := isolate(t)
		dir := filepath.Join(home, ".codex")
		os.MkdirAll(dir, 0o700)
		key := filepath.Join(dir, "hooks.json") + ":user_prompt_submit:0:0"
		os.WriteFile(filepath.Join(dir, "config.toml"), []byte("[hooks.state.\""+key+"\"]\ntrusted_hash = \"sha256:old\"\n"), 0o600)
		if _, err := wireCodex(context.Background(), "", testServer); err != nil {
			t.Fatal(err)
		}
		data, _ := os.ReadFile(filepath.Join(dir, "config.toml"))
		if strings.Contains(string(data), "sha256:old") || strings.Count(string(data), key) != 1 {
			t.Fatalf("got %s", data)
		}
	})
	t.Run("D5 GEMINI_CLI_HOME holds a .gemini directory", func(t *testing.T) {
		isolate(t)
		root := t.TempDir()
		t.Setenv("GEMINI_CLI_HOME", root)
		if _, err := wireGemini(context.Background(), "", testServer); err != nil {
			t.Fatal(err)
		}
		if _, err := os.Stat(filepath.Join(root, ".gemini", "settings.json")); err != nil {
			t.Fatal(err)
		}
	})
	t.Run("D6 legacy kimi with a named home is skipped and says why", func(t *testing.T) {
		isolate(t)
		bin := t.TempDir()
		kimi := filepath.Join(bin, "kimi")
		os.WriteFile(kimi, []byte("#!/bin/sh\necho 'kimi, version 1.52.0'\n"), 0o755)
		server := entry{Name: "elysian", Binary: "/opt/elysian-mcp", Env: map[string]string{"ELYSIAN_HOME": "/data"}}
		if action, err := registerKimi(context.Background(), kimi, server); err != nil || !strings.HasPrefix(action.Detail, "not registered") {
			t.Fatalf("got %+v %v", action, err)
		}
	})
}

func TestReviewOfP63RoundTwo(t *testing.T) {
	t.Run("D1 a re-run keeps every other Codex hook where its trust was recorded", func(t *testing.T) {
		home := isolate(t)
		if _, err := wireCodex(context.Background(), "", testServer); err != nil {
			t.Fatal(err)
		}
		path := filepath.Join(home, ".codex", "hooks.json")
		document := readJSON(t, path)
		hooks := document["hooks"].(map[string]any)
		hooks["UserPromptSubmit"] = append(hooks["UserPromptSubmit"].([]any), map[string]any{"hooks": []any{map[string]any{"type": "command", "command": "mine", "timeout": 5}}})
		data, _ := json.Marshal(document)
		os.WriteFile(path, data, 0o600)
		if _, err := wireCodex(context.Background(), "", testServer); err != nil {
			t.Fatal(err)
		}
		prompt := groups(t, readJSON(t, path), "UserPromptSubmit")
		if len(prompt) != 2 || !strings.Contains(mustJSON(prompt[0]), "elysian-mcp") || !strings.Contains(mustJSON(prompt[1]), `"mine"`) {
			t.Fatalf("the user's hook must stay at position 1, got %s", mustJSON(prompt))
		}
	})
	t.Run("D3 a trust header quoted another way is replaced, and an inline server stops before any write", func(t *testing.T) {
		home := isolate(t)
		dir := filepath.Join(home, ".codex")
		os.MkdirAll(dir, 0o700)
		key := filepath.Join(dir, "hooks.json") + ":session_start:0:0"
		config := filepath.Join(dir, "config.toml")
		os.WriteFile(config, []byte("[hooks.state.'"+key+"']\ntrusted_hash = \"sha256:old\"\n\n[mcp_servers.\"elysian\"]\ncommand = \"old\"\n"), 0o600)
		if _, err := wireCodex(context.Background(), "", testServer); err != nil {
			t.Fatal(err)
		}
		data, _ := os.ReadFile(config)
		if strings.Contains(string(data), "sha256:old") || strings.Contains(string(data), `"old"`) {
			t.Fatalf("got %s", data)
		}
		inline := "mcp_servers = { elysian = { command = \"x\" } }\n"
		os.WriteFile(config, []byte(inline), 0o600)
		hooksBefore, _ := os.ReadFile(filepath.Join(dir, "hooks.json"))
		if _, err := wireCodex(context.Background(), "", testServer); err == nil || !strings.Contains(err.Error(), "inline") {
			t.Fatalf("got %v", err)
		}
		if data, _ := os.ReadFile(config); string(data) != inline {
			t.Fatalf("a refused config must be left as it was, got %s", data)
		}
		if after, _ := os.ReadFile(filepath.Join(dir, "hooks.json")); string(after) != string(hooksBefore) {
			t.Fatal("a refusal must leave hooks.json as it was")
		}
	})
}

func TestReviewOfP63RoundThree(t *testing.T) {
	t.Run("D1 trust follows our group to the position it really holds", func(t *testing.T) {
		home := isolate(t)
		dir := filepath.Join(home, ".codex")
		os.MkdirAll(dir, 0o700)
		os.WriteFile(filepath.Join(dir, "hooks.json"), []byte(`{"hooks":{"UserPromptSubmit":[{"hooks":[{"type":"command","command":"/opt/elysian-mcp hook --client codex prompt","timeout":30}]},{"hooks":[{"type":"command","command":"mine","timeout":5}]}]}}`), 0o600)
		if _, err := wireCodex(context.Background(), "", testServer); err != nil {
			t.Fatal(err)
		}
		config, _ := os.ReadFile(filepath.Join(dir, "config.toml"))
		if !strings.Contains(string(config), ":user_prompt_submit:0:0") || strings.Contains(string(config), ":user_prompt_submit:1:0") {
			t.Fatalf("our prompt hook is at position 0, got %s", config)
		}
	})
	t.Run("D2 a header inside a multi-line string is the user's text", func(t *testing.T) {
		home := isolate(t)
		dir := filepath.Join(home, ".codex")
		os.MkdirAll(dir, 0o700)
		example := "developer_instructions = \"\"\"\nTo add a server:\n[mcp_servers.elysian]\ncommand = \"x\"\n\"\"\"\n"
		os.WriteFile(filepath.Join(dir, "config.toml"), []byte(example), 0o600)
		if _, err := wireCodex(context.Background(), "", testServer); err != nil {
			t.Fatal(err)
		}
		if config, _ := os.ReadFile(filepath.Join(dir, "config.toml")); !strings.HasPrefix(string(config), example) {
			t.Fatalf("the string must be kept whole, got %s", config)
		}
	})
	t.Run("D3 a commented opencode.jsonc stays untouched beside our opencode.json", func(t *testing.T) {
		home := isolate(t)
		dir := filepath.Join(home, ".config", "opencode")
		os.MkdirAll(dir, 0o700)
		jsonc := "{\n  // mine\n  \"theme\": \"dark\",\n}\n"
		os.WriteFile(filepath.Join(dir, "opencode.jsonc"), []byte(jsonc), 0o600)
		if _, err := registerOpenCode(context.Background(), "", testServer); err != nil {
			t.Fatal(err)
		}
		if data, _ := os.ReadFile(filepath.Join(dir, "opencode.jsonc")); string(data) != jsonc {
			t.Fatalf("got %s", data)
		}
		if !strings.Contains(mustJSON(readJSON(t, filepath.Join(dir, "opencode.json"))), `"elysian"`) {
			t.Fatal("our entry must be in opencode.json")
		}
	})
}
