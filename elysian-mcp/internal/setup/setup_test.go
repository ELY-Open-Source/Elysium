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
	script := "#!/bin/sh\necho \"$@\" >> \"" + filepath.Join(bin, name+".log") + "\"\n" +
		"if [ \"$2\" = remove ]; then " + remove + "; fi\n"
	if err := os.WriteFile(filepath.Join(bin, name), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
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
	result, err := Run(context.Background(), config.Config{Binary: "/opt/elysian-mcp"}, Options{})
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Actions) != 2 || result.Actions[0].Detail != "not installed; skipped" || result.Actions[1].Client != "claude" {
		t.Fatalf("codex must be skipped and claude registered, got %+v", result.Actions)
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
	if _, err := Run(context.Background(), config.Config{Binary: "/opt/elysian-mcp"}, Options{Home: "/data/elysian"}); err != nil {
		t.Fatalf("a re-run must replace the entries, got %v", err)
	}
	if calls := logged(t, bin, "codex"); !strings.Contains(calls, "mcp add elysian --env ELYSIAN_HOME=/data/elysian -- /opt/elysian-mcp server") {
		t.Fatalf("codex must carry the named home, got %q", calls)
	}
	if calls := logged(t, bin, "claude"); !strings.Contains(calls, `"env":{"ELYSIAN_HOME":"/data/elysian"}`) {
		t.Fatalf("claude must carry the named home, got %q", calls)
	}
}

func TestANamedClientThatIsMissingIsAnError(t *testing.T) {
	t.Setenv("PATH", t.TempDir())
	_, err := Run(context.Background(), config.Config{Binary: "/opt/elysian-mcp"}, Options{Client: "codex"})
	if err == nil || !strings.Contains(err.Error(), "codex is not on PATH") {
		t.Fatalf("a named missing client must be an error, got %v", err)
	}
}
