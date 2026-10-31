//go:build !windows

package backend

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"
)

func freePort(t *testing.T) string {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	return strconv.Itoa(listener.Addr().(*net.TCPAddr).Port)
}

func fakeElysian(t *testing.T, script string) string {
	t.Helper()
	bin := t.TempDir()
	if err := os.WriteFile(filepath.Join(bin, "elysian"), []byte("#!/bin/sh\n"+script), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+":/usr/bin:/bin")
	return bin
}

func status(home string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		_ = json.NewEncoder(w).Encode(map[string]string{"data_home": home})
	}
}

func TestARunningAPIIsLeftAlone(t *testing.T) {
	home := t.TempDir()
	api := httptest.NewServer(status(home))
	defer api.Close()
	t.Setenv("PATH", t.TempDir())
	if err := Ensure(context.Background(), api.URL, home); err != nil {
		t.Fatalf("a healthy API must need nothing started, got %v", err)
	}
}

func TestARunningAPIForAnotherStoreIsRefused(t *testing.T) {
	api := httptest.NewServer(status("/somewhere/else"))
	defer api.Close()
	err := Ensure(context.Background(), api.URL, t.TempDir())
	if err == nil || !strings.Contains(err.Error(), "serves /somewhere/else, not") {
		t.Fatalf("an API for another store must be refused, got %v", err)
	}
}

func TestTheLoserOfAPortRaceWaitsForTheWinner(t *testing.T) {
	home := t.TempDir()
	port := freePort(t)
	listener, err := net.Listen("tcp", "127.0.0.1:"+port)
	if err != nil {
		t.Fatal(err)
	}
	ready := time.Now().Add(2 * time.Second)
	winner := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if time.Now().Before(ready) {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		status(home)(w, r)
	})}
	go func() { _ = winner.Serve(listener) }()
	defer winner.Close()
	fakeElysian(t, "echo 'address already in use'\nexit 1\n")
	if err := Ensure(context.Background(), "http://127.0.0.1:"+port, home); err != nil {
		t.Fatalf("the loser must wait for the winner that holds the port, got %v", err)
	}
}

func TestOnlyALocalAPIIsStarted(t *testing.T) {
	err := Ensure(context.Background(), "http://192.0.2.1:9", t.TempDir())
	if err == nil || !strings.Contains(err.Error(), "only a local one can be started") {
		t.Fatalf("a remote API must not be started here, got %v", err)
	}
}

func TestAMissingElysianIsNamed(t *testing.T) {
	t.Setenv("PATH", t.TempDir())
	err := Ensure(context.Background(), "http://127.0.0.1:"+freePort(t), t.TempDir())
	if err == nil || !strings.Contains(err.Error(), "`elysian` is not on PATH") {
		t.Fatalf("a missing elysian must be named, got %v", err)
	}
}

func TestADownAPIIsStartedForTheSameHome(t *testing.T) {
	home := t.TempDir()
	if err := os.MkdirAll(filepath.Join(home, "www", "api"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(home, "www", "api", "status"), []byte(`{"data_home": "`+home+`"}`), 0o644); err != nil {
		t.Fatal(err)
	}
	fakeElysian(t, `echo "$$" > "$ELYSIAN_HOME/pid"; echo "serving $*"; cd "$ELYSIAN_HOME/www" && exec python3 -m http.server "$5" --bind "$3"`+"\n")
	t.Cleanup(func() {
		if raw, err := os.ReadFile(filepath.Join(home, "pid")); err == nil {
			if pid, err := strconv.Atoi(strings.TrimSpace(string(raw))); err == nil {
				_ = syscall.Kill(pid, syscall.SIGTERM)
			}
		}
	})
	url := "http://127.0.0.1:" + freePort(t)
	if err := Ensure(context.Background(), url, home); err != nil {
		t.Fatalf("a down API must be started, got %v", err)
	}
	log, err := os.ReadFile(filepath.Join(home, "logs", "api.log"))
	if err != nil || !strings.Contains(string(log), "serving serve --host 127.0.0.1 --port") {
		t.Fatalf("the API must log to <home>/logs/api.log, got %q, %v", log, err)
	}
}

func TestAnAPIThatDiesIsReportedWithItsLog(t *testing.T) {
	fakeElysian(t, "echo 'address already in use'\nexit 3\n")
	before := Wait
	Wait = 10 * time.Second
	t.Cleanup(func() { Wait = before })
	err := Ensure(context.Background(), "http://127.0.0.1:"+freePort(t), t.TempDir())
	if err == nil || !strings.Contains(err.Error(), "nothing holds") || !strings.Contains(err.Error(), "address already in use") {
		t.Fatalf("a dead API must be reported with its log, got %v", err)
	}
}
