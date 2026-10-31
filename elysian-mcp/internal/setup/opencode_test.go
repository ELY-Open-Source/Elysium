//go:build !windows

package setup

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// The 2.x plugin hears every location's session.created; alpha's slow hook must not land in beta's session.
func TestOpenCodePluginOpensEachSessionWithItsOwnFolder(t *testing.T) {
	node, err := exec.LookPath("node")
	if err != nil {
		t.Skip("node is not installed, so the OpenCode plugin cannot be run here")
	}
	dir := t.TempDir()
	hook := filepath.Join(dir, "hook")
	os.WriteFile(hook, []byte("#!/bin/sh\nread -r line\ncase \"$line\" in *alpha*) sleep 1; echo 'memories of alpha';; *) echo 'memories of beta';; esac\n"), 0o755)
	binary, _ := json.Marshal(hook)
	plugin := filepath.Join(dir, "plugin.mjs")
	os.WriteFile(plugin, []byte(strings.NewReplacer("__ELYSIAN_BINARY__", string(binary), "__ELYSIAN_HOME__", "null").Replace(openCodePlugin)), 0o600)
	harness, _ := filepath.Abs(filepath.Join("testdata", "opencode_locations.mjs"))
	if output, err := exec.Command(node, harness, plugin).CombinedOutput(); err != nil {
		t.Fatalf("%v: %s", err, output)
	}
}
