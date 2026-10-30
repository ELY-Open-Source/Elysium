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

func user(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	t.Setenv("HOME", filepath.Join(root, "user"))
	t.Setenv("ELYSIAN_HOME", "")
	if err := os.MkdirAll(filepath.Join(root, "project"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Chdir(filepath.Join(root, "project"))
	return root
}

func TestTheDefaultHomeIsTheUsersWhateverTheDirectory(t *testing.T) {
	root := user(t)
	home, err := resolveHome("")
	if err != nil || home != filepath.Join(root, "user", ".elysian") {
		t.Fatalf("the default home must be ~/.elysian, got %q, %v", home, err)
	}
}

func TestAProjectStoreIsNotPassedOverForTheGlobalOne(t *testing.T) {
	for _, name := range []string{".elysian", ".elysium", ".ely_eye"} {
		root := user(t)
		store(t, filepath.Join(root, "project", name, "data", "elysian.sqlite"))
		if _, err := resolveHome(""); err == nil || !strings.Contains(err.Error(), "holds a project store") {
			t.Fatalf("a project store in %s must stop the server, got %v", name, err)
		}
	}
}

func TestNamingTheProjectStoreOpensIt(t *testing.T) {
	root := user(t)
	project := filepath.Join(root, "project", ".elysian")
	store(t, filepath.Join(project, "data", "elysian.sqlite"))
	t.Setenv("ELYSIAN_HOME", project)
	if home, err := resolveHome(""); err != nil || home != project {
		t.Fatalf("ELYSIAN_HOME must open the named store, got %q, %v", home, err)
	}
}

func TestAnExplicitHomeWithAnOldDatabaseIsRefused(t *testing.T) {
	home := filepath.Join(t.TempDir(), ".elysian")
	store(t, filepath.Join(home, "data", "elysium.sqlite"))
	if _, err := resolveHome(home); err == nil || !strings.Contains(err.Error(), "elysium.sqlite is a store from before the rename") {
		t.Fatalf("an old database in the given home must be refused, got %v", err)
	}
	store(t, filepath.Join(home, "data", "elysian.sqlite"))
	if _, err := resolveHome(home); err != nil {
		t.Fatalf("a moved store must open, got %v", err)
	}
}
