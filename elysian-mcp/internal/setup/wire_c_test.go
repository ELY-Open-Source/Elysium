//go:build !windows

package setup

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestGrokGetsServerPermissionHookAndRuleOnceAndKeepsTheUsersOwn(t *testing.T) {
	home := isolate(t)
	dir := filepath.Join(home, ".grok")
	os.MkdirAll(dir, 0o700)
	os.WriteFile(filepath.Join(dir, "config.toml"), []byte("model = \"grok-4\"\n"), 0o600)
	for range 2 {
		if _, err := registerGrok(context.Background(), "", testServer); err != nil {
			t.Fatal(err)
		}
	}
	config, _ := os.ReadFile(filepath.Join(dir, "config.toml"))
	if text := string(config); !strings.HasPrefix(text, "model = \"grok-4\"") || strings.Count(text, "[mcp_servers.elysian]") != 1 || !strings.Contains(text, `allow = ["MCPTool(elysian__*)"]`) {
		t.Fatalf("got %s", text)
	}
	if hook := mustJSON(readJSON(t, filepath.Join(dir, "hooks", "elysian.json"))); !strings.Contains(hook, "hook --client grok prompt") {
		t.Fatalf("got %s", hook)
	}
	if rule, _ := os.ReadFile(filepath.Join(dir, "rules", "elysian.md")); !strings.Contains(string(rule), "search_atoms") {
		t.Fatalf("got %s", rule)
	}
	os.WriteFile(filepath.Join(dir, "config.toml"), []byte("[permission]\nallow = [\"Bash(ls)\"]\n\n[mcp_servers.elysian]\ncommand = \"x\"\n"), 0o600)
	action, err := registerGrok(context.Background(), "", testServer)
	config, _ = os.ReadFile(filepath.Join(dir, "config.toml"))
	if err != nil || strings.Count(string(config), "[permission]") != 1 || strings.Count(string(config), "[mcp_servers.elysian]") != 1 || !strings.Contains(action.Detail, "by hand") {
		t.Fatalf("a table the user wrote must not be defined twice, got %+v %v\n%s", action, err, config)
	}
}

func TestCommunityGrokIsNamedAndKigiKeepsItsAgentsFile(t *testing.T) {
	home := isolate(t)
	os.MkdirAll(filepath.Join(home, ".grok"), 0o700)
	os.WriteFile(filepath.Join(home, ".grok", "user-settings.json"), []byte("{}"), 0o600)
	if action, err := registerGrok(context.Background(), "", testServer); err != nil || !strings.Contains(action.Detail, "community grok-cli") {
		t.Fatalf("got %+v %v", action, err)
	}
	agents := filepath.Join(home, ".kigi", "AGENTS.md")
	os.MkdirAll(filepath.Dir(agents), 0o700)
	os.WriteFile(agents, []byte("# My rules\nBe brief.\n"), 0o600)
	for range 2 {
		if _, err := registerKigi(context.Background(), "", testServer); err != nil {
			t.Fatal(err)
		}
	}
	text, _ := os.ReadFile(agents)
	if !strings.HasPrefix(string(text), "# My rules\nBe brief.\n") || strings.Count(string(text), "<!-- >>> elysian") != 1 || !strings.HasSuffix(string(text), "<!-- <<< elysian -->\n") {
		t.Fatalf("got %s", text)
	}
}
