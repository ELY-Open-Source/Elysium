package setup

import "testing"

// The expected value is what Codex 0.166 wrote to config.toml when a user trusted this hook in /hooks.
func TestCodexHookHashMatchesWhatCodexStoresOnTrust(t *testing.T) {
	got, err := codexHookHash("session_start", "", "bash '/home/raidenmei/.codex/herdr-agent-state.sh' session", 10)
	if err != nil {
		t.Fatal(err)
	}
	if want := "sha256:0abf4ed6bba124502b48a0095b2e1f40d372c9cec60a8e55feaac8364e50163d"; got != want {
		t.Fatalf("got %s, want %s", got, want)
	}
}
