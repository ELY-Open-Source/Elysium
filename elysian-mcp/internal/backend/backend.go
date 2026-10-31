// Package backend starts the Elysian API when the MCP server finds it down.
package backend

import (
	"bufio"
	"context"
	"errors"
	"fmt"
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
	if healthy(ctx, baseURL) {
		return nil
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
	exited := make(chan error, 1)
	go func() { exited <- command.Wait() }()
	deadline := time.Now().Add(Wait)
	for time.Now().Before(deadline) {
		if healthy(ctx, baseURL) {
			return nil
		}
		select {
		case err := <-exited:
			if healthy(ctx, baseURL) {
				return nil
			}
			return fmt.Errorf("`elysian serve` exited (%v) before the API answered; last lines of %s:\n%s", err, logPath, tail(logPath))
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(250 * time.Millisecond):
		}
	}
	return fmt.Errorf("`elysian serve` did not answer at %s within %s; last lines of %s:\n%s", baseURL, Wait, logPath, tail(logPath))
}

func healthy(ctx context.Context, baseURL string) bool {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, strings.TrimRight(baseURL, "/")+"/api/status", nil)
	if err != nil {
		return false
	}
	response, err := (&http.Client{Timeout: 2 * time.Second}).Do(request)
	if err != nil {
		return false
	}
	response.Body.Close()
	return response.StatusCode == http.StatusOK
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
