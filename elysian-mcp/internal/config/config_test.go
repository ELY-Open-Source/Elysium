package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAnOldVariableNamesItsNewSpelling(t *testing.T) {
	for _, old := range []string{"ELY_EYE_AUTH_TOKEN", "ELYSIUM_AUTH_TOKEN"} {
		err := refuseOldNames([]string{"PATH=/bin", old + "=secret"})
		if err == nil || !strings.Contains(err.Error(), old+" is set") || !strings.Contains(err.Error(), "reads ELYSIAN_AUTH_TOKEN") {
			t.Fatalf("%s must stop the server and name its new spelling, got %v", old, err)
		}
	}
}

func TestOnlyTheNewNamesPass(t *testing.T) {
	if err := refuseOldNames([]string{"ELYSIAN_AUTH_TOKEN=secret", "HOME=/root"}); err != nil {
		t.Fatalf("the new names must pass, got %v", err)
	}
}

func store(t *testing.T, path string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte("store"), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestAnOldStoreIsNotPassedOverForOneHigherUp(t *testing.T) {
	for _, old := range []string{".elysium/data/elysium.sqlite", ".elysian/data/elysium.sqlite", ".ely_eye/data/ely_eye.sqlite"} {
		root := t.TempDir()
		store(t, filepath.Join(root, ".elysian", "data", "elysian.sqlite"))
		child := filepath.Join(root, "project")
		store(t, filepath.Join(child, old))
		t.Chdir(child)
		home, err := discoverHome()
		if err == nil || !strings.Contains(err.Error(), "from before the rename") {
			t.Fatalf("%s must stop the walk up, got home %q and error %v", old, home, err)
		}
	}
}

func TestAnExplicitHomeWithAnOldDatabaseIsRefused(t *testing.T) {
	home := filepath.Join(t.TempDir(), ".elysian")
	store(t, filepath.Join(home, "data", "elysium.sqlite"))
	if _, err := resolveHome("", home); err == nil || !strings.Contains(err.Error(), "elysium.sqlite is a store from before the rename") {
		t.Fatalf("an old database in the given home must be refused, got %v", err)
	}
	store(t, filepath.Join(home, "data", "elysian.sqlite"))
	if _, err := resolveHome("", home); err != nil {
		t.Fatalf("a moved store must open, got %v", err)
	}
}
