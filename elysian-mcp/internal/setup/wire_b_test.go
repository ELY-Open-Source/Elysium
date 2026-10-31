//go:build !windows

package setup

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestKiroGetsApprovedServerGlobalHooksAndItsRuleWhereTheLayoutAllows(t *testing.T) {
	home := isolate(t)
	if _, err := registerKiro(context.Background(), "", testServer); err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(home, ".kiro")
	spec := readJSON(t, filepath.Join(dir, "settings", "mcp.json"))["mcpServers"].(map[string]any)["elysian"].(map[string]any)
	if spec["disabled"] != false || mustJSON(spec["autoApprove"]) != `["*"]` {
		t.Fatalf("got %+v", spec)
	}
	hooks := readJSON(t, filepath.Join(dir, "hooks", "elysian.json"))
	if hooks["version"] != "v1" || !strings.Contains(mustJSON(hooks["hooks"]), `"trigger":"UserPromptSubmit"`) {
		t.Fatalf("got %s", mustJSON(hooks))
	}
	permissions, _ := os.ReadFile(filepath.Join(dir, "settings", "permissions.yaml"))
	if string(permissions) != "rules:\n  - capability: mcp\n    match: [\"elysian/*\"]\n    effect: allow\n" {
		t.Fatalf("got %q", permissions)
	}
	path := filepath.Join(dir, "settings", "permissions.yaml")
	os.WriteFile(path, []byte("rules:\n- capability: shell\n  effect: ask\n"), 0o600)
	if _, err := registerKiro(context.Background(), "", testServer); err != nil {
		t.Fatal(err)
	}
	if data, _ := os.ReadFile(path); string(data) != "rules:\n- capability: shell\n  effect: ask\n- capability: mcp\n  match: [\"elysian/*\"]\n  effect: allow\n" {
		t.Fatalf("got %q", data)
	}
	os.WriteFile(path, []byte("rules:\n  - capability: shell\ndefault: ask\n"), 0o600)
	action, err := registerKiro(context.Background(), "", testServer)
	if err != nil || !strings.Contains(action.Detail, "by hand") {
		t.Fatalf("an unknown layout must be named, got %+v %v", action, err)
	}
	if data, _ := os.ReadFile(path); string(data) != "rules:\n  - capability: shell\ndefault: ask\n" {
		t.Fatalf("an unknown layout must be left alone, got %q", data)
	}
}

func TestAntigravityGetsServerPermissionAndANamedHookSet(t *testing.T) {
	home := isolate(t)
	path := filepath.Join(home, ".gemini", "config", "hooks.json")
	os.MkdirAll(filepath.Dir(path), 0o700)
	os.WriteFile(path, []byte(`{"mine":{"Stop":[]}}`), 0o600)
	if _, err := registerAntigravity(context.Background(), "", testServer); err != nil {
		t.Fatal(err)
	}
	hooks := readJSON(t, path)
	if hooks["mine"] == nil || !strings.Contains(mustJSON(hooks["elysian"]), `"PreInvocation"`) {
		t.Fatalf("got %s", mustJSON(hooks))
	}
	settings := readJSON(t, filepath.Join(home, ".gemini", "antigravity-cli", "settings.json"))
	if mustJSON(settings["permissions"]) != `{"allow":["mcp(elysian/*)"]}` {
		t.Fatalf("got %s", mustJSON(settings))
	}
}

func TestKimiCodeGetsServerRuleAndPromptHookAndLegacyKimiOnlyTheServer(t *testing.T) {
	home := isolate(t)
	bin := t.TempDir()
	kimi := filepath.Join(bin, "kimi")
	os.WriteFile(kimi, []byte("#!/bin/sh\nif [ \"$1\" = --version ]; then echo 'kimi-code 2.4.1'; exit 0; fi\necho \"$@\" >> \""+bin+"/kimi.log\"\n"), 0o755)
	for range 2 {
		if _, err := registerKimi(context.Background(), kimi, testServer); err != nil {
			t.Fatal(err)
		}
	}
	config, _ := os.ReadFile(filepath.Join(home, ".kimi-code", "config.toml"))
	if strings.Count(string(config), "[[hooks]]") != 1 || !strings.Contains(string(config), `pattern = "mcp__elysian__*"`) ||
		!strings.Contains(string(config), `command = "/opt/elysian-mcp hook --client kimi prompt"`) {
		t.Fatalf("got %s", config)
	}
	os.WriteFile(kimi, []byte("#!/bin/sh\nif [ \"$1\" = --version ]; then echo 'kimi, version 1.52.0'; exit 0; fi\necho \"$@\" >> \""+bin+"/kimi.log\"\n"), 0o755)
	action, err := registerKimi(context.Background(), kimi, testServer)
	if err != nil || !strings.Contains(action.Detail, "kimi migrate") || logged(t, bin, "kimi") != "mcp add elysian -- /opt/elysian-mcp server\n" {
		t.Fatalf("got %+v %v %q", action, err, logged(t, bin, "kimi"))
	}
}

func TestCopilotAndCursorGetHooksAndKeepTheirOtherEntries(t *testing.T) {
	home := isolate(t)
	if _, err := registerCopilot(context.Background(), "", testServer); err != nil {
		t.Fatal(err)
	}
	hooks := readJSON(t, filepath.Join(home, ".copilot", "hooks", "elysian.json"))
	if text := mustJSON(hooks); !strings.Contains(text, `"permissionRequest"`) || !strings.Contains(text, `"powershell":"& /opt/elysian-mcp hook --client copilot prompt"`) {
		t.Fatalf("got %s", text)
	}
	cursor := filepath.Join(home, ".cursor")
	os.MkdirAll(cursor, 0o700)
	os.WriteFile(filepath.Join(cursor, "hooks.json"), []byte(`{"version":1,"hooks":{"stop":[{"command":"mine"}],"beforeSubmitPrompt":[{"command":"mine too"}]}}`), 0o600)
	os.WriteFile(filepath.Join(cursor, "cli-config.json"), []byte(`{"permissions":{"allow":["Shell(ls)"]}}`), 0o600)
	for range 2 {
		if _, err := wireCursor(filepath.Join(cursor, "mcp.json"), testServer); err != nil {
			t.Fatal(err)
		}
	}
	text := mustJSON(readJSON(t, filepath.Join(cursor, "hooks.json")))
	if !strings.Contains(text, `"stop":[{"command":"mine"}]`) || strings.Count(text, "hook --client cursor prompt") != 1 || !strings.Contains(text, `"mine too"`) {
		t.Fatalf("got %s", text)
	}
	if allow := mustJSON(readJSON(t, filepath.Join(cursor, "cli-config.json"))["permissions"]); allow != `{"allow":["Shell(ls)","Mcp(elysian:*)"]}` {
		t.Fatalf("got %s", allow)
	}
}
