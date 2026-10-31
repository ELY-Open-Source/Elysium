// Package hook is what a coding agent runs on its lifecycle events: it recalls memories into the
// agent's context and saves what the user said, so memory works without the model choosing to.
package hook

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/apiclient"
	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/backend"
	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/config"
	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/domain"
)

// Event is the moment in the agent's turn a hook runs at.
type Event string

const (
	SessionStart Event = "session-start"
	Prompt       Event = "prompt"
	Approve      Event = "approve"
)

// Input is what every dialect reads out of its client's payload.
type Input struct {
	Prompt    string
	SessionID string
	Cwd       string
}

// promptBudget keeps a prompt hook inside the shortest client timeout; the API answers in well under it.
const promptBudget = 4 * time.Second

// Run reads one hook payload from stdin and writes the client's answer to stdout.
func Run(ctx context.Context, cfg config.Config, client string, event Event, stdin io.Reader, stdout io.Writer) error {
	d, ok := dialects[client]
	if !ok {
		return fmt.Errorf("no hook dialect for client %q; known: %s", client, strings.Join(clientNames(), ", "))
	}
	raw, err := readPayload(stdin)
	if err != nil {
		return err
	}
	if d.foreign != nil && d.foreign(raw) {
		return nil
	}
	if event == Approve {
		if d.approve == nil {
			return fmt.Errorf("%s approves Elysian's tools through its own settings, not a hook", client)
		}
		return d.approve(stdout, raw)
	}
	in := d.read(raw)
	if in.Cwd == "" {
		if in.Cwd, err = os.Getwd(); err != nil {
			return err
		}
	}
	api := apiclient.New(cfg.APIBaseURL)
	api.Token = cfg.Token
	var extra string
	switch event {
	case SessionStart:
		if err := backend.Ensure(ctx, cfg.APIBaseURL, cfg.ElysianHome); err != nil {
			return err
		}
		extra, err = sessionContext(ctx, api, project(in.Cwd))
	case Prompt:
		extra, err = promptTurn(ctx, cfg, api, client, d, in)
	default:
		return fmt.Errorf("hook event must be session-start, prompt or approve, got %q", event)
	}
	if err != nil {
		return err
	}
	return d.write(stdout, event, extra)
}

// promptTurn runs once per user prompt: open the session where the client has no session hook,
// recall, then save, so nothing this turn writes is recalled by it.
func promptTurn(ctx context.Context, cfg config.Config, api *apiclient.Client, client string, d dialect, in Input) (string, error) {
	bounded, cancel := context.WithTimeout(ctx, promptBudget)
	defer cancel()
	if err := backend.Verify(bounded, cfg.APIBaseURL, cfg.ElysianHome); err != nil {
		return "", err
	}
	seen := &marker{home: cfg.ElysianHome, purpose: "prompt", client: client, session: in.SessionID, value: in.Prompt}
	if d.repeats {
		claimed, err := seen.claim()
		if err != nil || !claimed {
			return "", err
		}
		defer seen.release()
	}
	if d.captureOnly {
		if err := save(bounded, api, client, in); err != nil {
			return "", err
		}
		return "", nil
	}
	var parts []string
	opened := marker{home: cfg.ElysianHome, purpose: "session", client: client, session: in.SessionID}
	opening := false
	if d.noSessionHook {
		done, err := opened.done()
		if err != nil {
			return "", err
		}
		if !done {
			session, err := sessionContext(bounded, api, project(in.Cwd))
			if err != nil {
				return "", err
			}
			parts, opening = append(parts, session), true
		}
	}
	recalled, err := promptContext(bounded, api, client, in)
	if err != nil {
		return "", err
	}
	if opening {
		if err := opened.mark(); err != nil {
			return "", err
		}
	}
	if d.repeats {
		if err := seen.mark(); err != nil {
			return "", err
		}
	}
	return strings.TrimSpace(strings.Join(append(parts, recalled), "\n")), nil
}

// readPayload decodes the client's JSON; an empty stdin is an empty payload, broken JSON is an error.
func readPayload(stdin io.Reader) (map[string]any, error) {
	data, err := io.ReadAll(io.LimitReader(stdin, 8<<20))
	if err != nil {
		return nil, err
	}
	raw := map[string]any{}
	if strings.TrimSpace(string(data)) == "" {
		return raw, nil
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, errors.New("the hook payload on stdin is not a JSON object: " + err.Error())
	}
	return raw, nil
}

// sessionContext opens a session with what this project already holds and how memory works here.
func sessionContext(ctx context.Context, api *apiclient.Client, scenario string) (string, error) {
	lines := []string{"Elysian local memory is connected (MCP server `elysian`). What the user says in this session is saved to it automatically, and memories that match each prompt are added here. Call `remember` for a durable fact the user did not state, and `search_atoms` or `ask` to look further."}
	result, err := api.Search(ctx, apiclient.SearchOptions{Query: scenario, Scenario: scenario, Limit: 6})
	if err != nil {
		return "", err
	}
	if recalled := recall(result.Hits, ""); recalled != "" {
		lines = append(lines, "Memories from earlier sessions in "+scenario+":", recalled)
	}
	return strings.Join(lines, "\n"), nil
}

// promptContext recalls for the prompt first, then saves it, so a prompt never recalls itself.
func promptContext(ctx context.Context, api *apiclient.Client, client string, in Input) (string, error) {
	text := strings.TrimSpace(in.Prompt)
	if text == "" {
		return "", errors.New("the hook payload carries no prompt text")
	}
	result, err := api.Search(ctx, apiclient.SearchOptions{Query: text, Limit: 5})
	if err != nil {
		return "", err
	}
	if err := save(ctx, api, client, in); err != nil {
		return "", err
	}
	recalled := recall(result.Hits, text)
	if recalled == "" {
		return "", nil
	}
	return "Elysian local memory, recalled for this prompt (check before relying on it):\n" + recalled, nil
}

// save stores what the user said, filed under the project and the client's session.
func save(ctx context.Context, api *apiclient.Client, client string, in Input) error {
	statement, ok := capturable(in.Prompt)
	if !ok {
		return nil
	}
	body := map[string]any{"text": statement, "scenario": project(in.Cwd), "session_id": client + ":" + in.SessionID}
	var saved domain.Memory
	return api.Post(ctx, "/api/memory", body, &saved)
}

// marker remembers, per client session and purpose, the last value a hook finished with; it is
// written only after the work succeeds, so a failed turn is retried rather than skipped.
type marker struct {
	home, purpose, client, session, value string
	lock                                  *os.File
}

func (m marker) path() (string, string) {
	key := sha256.Sum256([]byte(m.purpose + "\n" + m.client + "\n" + m.session))
	digest := sha256.Sum256([]byte(m.value))
	return filepath.Join(m.home, "hooks", "seen", hex.EncodeToString(key[:8])), hex.EncodeToString(digest[:])
}

func (m marker) done() (bool, error) {
	path, want := m.path()
	last, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return false, nil
	}
	return err == nil && string(last) == want, err
}

func (m marker) mark() error {
	path, want := m.path()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	return os.WriteFile(path, []byte(want), 0o600)
}

// claim waits for the session's lock, then takes this value unless it was already finished, so hooks
// fired together recall and save once. The lock is the kernel's: a process that dies drops it.
func (m *marker) claim() (bool, error) {
	path, _ := m.path()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return false, err
	}
	file, err := os.OpenFile(path+".lock", os.O_CREATE|os.O_RDWR, 0o600)
	if err != nil {
		return false, err
	}
	if err := lockFile(file); err != nil {
		file.Close()
		return false, err
	}
	m.lock = file
	done, err := m.done()
	if err != nil || done {
		m.release()
		return false, err
	}
	return true, nil
}

// release drops the lock whether the work succeeded or not; only mark records success.
func (m *marker) release() {
	if m.lock != nil {
		_ = unlockFile(m.lock)
		_ = m.lock.Close()
		m.lock = nil
	}
}

// project names the scenario a memory is filed under: the git root's name, else the folder's.
func project(cwd string) string {
	for dir := cwd; ; dir = filepath.Dir(dir) {
		if _, err := os.Stat(filepath.Join(dir, ".git")); err == nil {
			return filepath.Base(dir)
		}
		if parent := filepath.Dir(dir); parent == dir {
			return filepath.Base(cwd)
		}
	}
}
