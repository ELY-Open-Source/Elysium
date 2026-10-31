// Package backend starts the Elysian API when the MCP server finds it down.
package backend

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// Wait is how long a fresh API gets to answer; its first start creates the store.
var Wait = 90 * time.Second

// Ensure returns once the API at baseURL answers, starting `elysian serve` for home if it does not.
func Ensure(ctx context.Context, baseURL string, home string) error {
	if served, ok := serving(ctx, baseURL); ok {
		return sameStore(baseURL, served, home)
	}
	address, err := url.Parse(baseURL)
	if err != nil {
		return fmt.Errorf("ELYSIAN_API %q is not a URL: %w", baseURL, err)
	}
	if host := address.Hostname(); host != "127.0.0.1" && host != "localhost" {
		return errors.New("the Elysian API at " + baseURL + " is unreachable, and only a local one can be started here")
	}
	program, err := exec.LookPath("elysian")
	if err != nil {
		return errors.New("the Elysian API at " + baseURL + " is down and `elysian` is not on PATH; run the installer or start `elysian serve`")
	}
	logPath := filepath.Join(home, "logs", "api.log")
	if err := os.MkdirAll(filepath.Dir(logPath), 0o700); err != nil {
		return err
	}
	log, err := os.OpenFile(logPath, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return err
	}
	defer log.Close()
	command := exec.Command(program, "serve", "--host", address.Hostname(), "--port", address.Port())
	command.Env = append(os.Environ(), "ELYSIAN_HOME="+home)
	command.Stdout, command.Stderr = log, log
	detach(command)
	if err := command.Start(); err != nil {
		return fmt.Errorf("cannot start %s serve: %w", program, err)
	}
	fmt.Fprintf(os.Stderr, "elysian-mcp: started `elysian serve` (pid %d) for %s; log %s\n", command.Process.Pid, baseURL, logPath)
	exitedWith := make(chan error, 1)
	go func() { exitedWith <- command.Wait() }()
	var exitErr error
	exited := false
	deadline := time.Now().Add(Wait)
	for time.Now().Before(deadline) {
		if served, ok := serving(ctx, baseURL); ok {
			return sameStore(baseURL, served, home)
		}
		// A child that lost the port race exits; the winner still holds the port while it starts.
		if exited && !listening(address.Host) {
			return fmt.Errorf("`elysian serve` exited (%v) and nothing holds %s; last lines of %s:\n%s", exitErr, address.Host, logPath, tail(logPath))
		}
		select {
		case exitErr = <-exitedWith:
			exited = true
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(250 * time.Millisecond):
		}
	}
	return fmt.Errorf("`elysian serve` did not answer at %s within %s; last lines of %s:\n%s", baseURL, Wait, logPath, tail(logPath))
}

// sameStore refuses an API that serves another home: its writes would land in the wrong store.
func sameStore(baseURL string, served string, home string) error {
	if !filepath.IsAbs(served) {
		return errors.New("the Elysian API at " + baseURL + " reports the relative home " + served + ", so its store cannot be told from here; restart it with this build")
	}
	if real(served) != real(home) {
		return errors.New("the Elysian API at " + baseURL + " serves " + served + ", not " + home + "; stop it or point ELYSIAN_API at another port")
	}
	return nil
}

func real(path string) string {
	if resolved, err := filepath.EvalSymlinks(path); err == nil {
		return resolved
	}
	return path
}

func listening(host string) bool {
	connection, err := net.DialTimeout("tcp", host, time.Second)
	if err != nil {
		return false
	}
	connection.Close()
	return true
}

// serving reports whether the API answers at baseURL and which home it serves.
func serving(ctx context.Context, baseURL string) (string, bool) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(baseURL, "/")+"/api/status", nil)
	if err != nil {
		return "", false
	}
	response, err := (&http.Client{Timeout: 2 * time.Second}).Do(request)
	if err != nil {
		return "", false
	}
	defer response.Body.Close()
	var status struct {
		DataHome string `json:"data_home"`
	}
	if response.StatusCode != http.StatusOK || json.NewDecoder(response.Body).Decode(&status) != nil || status.DataHome == "" {
		return "", false
	}
	return status.DataHome, true
}

func tail(path string) string {
	file, err := os.Open(path)
	if err != nil {
		return err.Error()
	}
	defer file.Close()
	var lines []string
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		lines = append(lines, scanner.Text())
		if len(lines) > 20 {
			lines = lines[1:]
		}
	}
	return strings.Join(lines, "\n")
}
