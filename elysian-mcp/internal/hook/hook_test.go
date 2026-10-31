package hook

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/config"
)

// fakeAPI answers search with one stored memory and records every save and search.
type fakeAPI struct {
	mu       sync.Mutex
	saved    []map[string]any
	searches int
	order    []string
	served   string
}

func serve(t *testing.T, home string) (*fakeAPI, config.Config) {
	t.Helper()
	api := &fakeAPI{served: home}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		api.mu.Lock()
		defer api.mu.Unlock()
		switch r.URL.Path {
		case "/api/status":
			json.NewEncoder(w).Encode(map[string]any{"data_home": api.served})
		case "/api/search":
			api.searches++
			api.order = append(api.order, "search")
			json.NewEncoder(w).Encode(map[string]any{"status": "hits", "hits": []any{map[string]any{
				"atom": map[string]any{"text": "The release branch is release/2026.", "ingested_at": "2026-10-30T09:00:00Z", "scenario": "demo"}, "final_score": 1.0,
			}}})
		case "/api/memory":
			var body map[string]any
			json.NewDecoder(r.Body).Decode(&body)
			api.saved = append(api.saved, body)
			api.order = append(api.order, "save")
			json.NewEncoder(w).Encode(map[string]any{"atom_id": "a1", "text": body["text"]})
		default:
			http.NotFound(w, r)
		}
	}))
	t.Cleanup(server.Close)
	return api, config.Config{APIBaseURL: server.URL, ElysianHome: home, Token: "t"}
}

func run(t *testing.T, cfg config.Config, client string, event Event, payload string) string {
	t.Helper()
	var out bytes.Buffer
	if err := Run(context.Background(), cfg, client, event, strings.NewReader(payload), &out); err != nil {
		t.Fatalf("%s %s: %v", client, event, err)
	}
	return out.String()
}

const statement = `"prompt":"We ship from release/2026 and run install_acceptance first.","session_id":"s1","cwd":"/tmp/demo"`

func TestClaudePromptRecallsThenSavesInHookSpecificShape(t *testing.T) {
	api, cfg := serve(t, t.TempDir())
	out := run(t, cfg, "claude", Prompt, "{"+statement+"}")
	var answer struct {
		HookSpecificOutput struct{ HookEventName, AdditionalContext string }
	}
	if err := json.Unmarshal([]byte(out), &answer); err != nil {
		t.Fatalf("not JSON: %q", out)
	}
	if answer.HookSpecificOutput.HookEventName != "UserPromptSubmit" || !strings.Contains(answer.HookSpecificOutput.AdditionalContext, "release/2026") {
		t.Fatalf("got %+v", answer)
	}
	if len(api.saved) != 1 || api.saved[0]["scenario"] != "demo" || api.saved[0]["session_id"] != "claude:s1" {
		t.Fatalf("saved %+v", api.saved)
	}
}

func TestEachClientGetsItsOwnShape(t *testing.T) {
	_, cfg := serve(t, t.TempDir())
	cases := map[string]string{
		"kiro":    "Elysian local memory, recalled",
		"copilot": `{"additionalContext":`,
		"cursor":  `"continue":true`,
		"gemini":  `"hookEventName":"BeforeAgent"`,
		"codex":   `"hookEventName":"UserPromptSubmit"`,
	}
	for client, want := range cases {
		if out := run(t, cfg, client, Prompt, "{"+statement+"}"); !strings.Contains(out, want) {
			t.Fatalf("%s: want %q in %q", client, want, out)
		}
	}
	agy := run(t, cfg, "agy", Prompt, `{"lastUserInput":"We ship from release/2026 on Fridays.","conversationId":"c1","workspacePaths":["/tmp/demo"]}`)
	if !strings.Contains(agy, `"injectSteps":[{"ephemeralMessage":`) {
		t.Fatalf("agy got %q", agy)
	}
}

func TestAntigravityRecallsOncePerPromptThoughItFiresEveryModelCall(t *testing.T) {
	api, cfg := serve(t, t.TempDir())
	payload := `{"lastUserInput":"We ship from release/2026 on Fridays.","conversationId":"c1"}`
	first := run(t, cfg, "agy", Prompt, payload)
	second := run(t, cfg, "agy", Prompt, payload)
	if first == "" || second != "" || api.searches != 1 || len(api.saved) != 1 {
		t.Fatalf("first %q second %q searches %d saved %d", first, second, api.searches, len(api.saved))
	}
}

func TestKimiOpensTheSessionOnItsFirstPromptAndJoinsPromptParts(t *testing.T) {
	api, cfg := serve(t, t.TempDir())
	payload := `{"prompt":[{"type":"text","text":"We ship from release/2026"},{"type":"text","text":"and run install_acceptance first."}],"session_id":"k1","cwd":"/tmp/demo"}`
	first := run(t, cfg, "kimi", Prompt, payload)
	second := run(t, cfg, "kimi", Prompt, payload)
	if !strings.Contains(first, "Elysian local memory is connected") || strings.Contains(second, "is connected") {
		t.Fatalf("first %q\nsecond %q", first, second)
	}
	if api.saved[0]["text"] != "We ship from release/2026\nand run install_acceptance first." {
		t.Fatalf("saved %+v", api.saved[0])
	}
}

func TestGrokOnlySavesBecauseItDiscardsPromptOutput(t *testing.T) {
	api, cfg := serve(t, t.TempDir())
	out := run(t, cfg, "grok", Prompt, `{"prompt":"We ship from release/2026 on Fridays.","sessionId":"g1","cwd":"/tmp/demo"}`)
	if out != "" || api.searches != 0 || len(api.saved) != 1 || api.saved[0]["session_id"] != "grok:g1" {
		t.Fatalf("out %q searches %d saved %+v", out, api.searches, api.saved)
	}
}

func TestClaudeHooksStepAsideInsideCursorGrokAndKigi(t *testing.T) {
	api, cfg := serve(t, t.TempDir())
	for _, payload := range []string{`{"cursor_version":"3.25",` + statement + `}`, `{"hookEventName":"UserPromptSubmit",` + statement + `}`} {
		if out := run(t, cfg, "claude", Prompt, payload); out != "" {
			t.Fatalf("got %q", out)
		}
	}
	if api.searches != 0 || len(api.saved) != 0 {
		t.Fatalf("a borrowed run touched memory: %d searches, %d saves", api.searches, len(api.saved))
	}
}

func TestCopilotApprovesOnlyElysiansTools(t *testing.T) {
	_, cfg := serve(t, t.TempDir())
	if out := run(t, cfg, "copilot", Approve, `{"toolName":"elysian-search_atoms"}`); !strings.Contains(out, `"behavior":"allow"`) {
		t.Fatalf("got %q", out)
	}
	if out := run(t, cfg, "copilot", Approve, `{"toolName":"shell"}`); out != "" {
		t.Fatalf("another tool must be left to Copilot, got %q", out)
	}
}

func TestSessionStartNamesTheProjectsMemories(t *testing.T) {
	home := t.TempDir()
	_, cfg := serve(t, home)
	out := run(t, cfg, "claude", SessionStart, `{"session_id":"s1","cwd":"/tmp/demo","source":"startup"}`)
	if !strings.Contains(out, "is connected") || !strings.Contains(out, "Memories from earlier sessions in demo") {
		t.Fatalf("got %q", out)
	}
}

func TestCaptureSkipsCommandsRepliesAndShortQuestionsAndMasksSecrets(t *testing.T) {
	for _, skipped := range []string{"/compact", "!ls", "ok", "继续", "发布前要跑什么检查？", "what branch do we ship from?", `"Which host does the staging database live on?"`} {
		if _, ok := capturable(skipped); ok {
			t.Fatalf("%q must not be saved", skipped)
		}
	}
	text, ok := capturable("Deploy with token=abcd1234efgh5678 and key sk-ABCDEFGHIJKLMNOPQRSTUV please")
	if !ok || strings.Contains(text, "abcd1234") || strings.Contains(text, "sk-ABC") {
		t.Fatalf("got %q", text)
	}
}

func TestUnknownClientAndBrokenPayloadAreNamed(t *testing.T) {
	_, cfg := serve(t, t.TempDir())
	var out bytes.Buffer
	if err := Run(context.Background(), cfg, "notepad", Prompt, strings.NewReader("{}"), &out); err == nil || !strings.Contains(err.Error(), "known: agy") {
		t.Fatalf("got %v", err)
	}
	if err := Run(context.Background(), cfg, "claude", Prompt, strings.NewReader("{not json"), &out); err == nil || !strings.Contains(err.Error(), "not a JSON object") {
		t.Fatalf("got %v", err)
	}
	if FailExit("kiro") != 0 || FailExit("claude") != 1 {
		t.Fatal("kiro must fail with 0, claude with 1")
	}
}

func TestAFailedTurnIsRetriedNotSkippedAndJSONSecretsAreMasked(t *testing.T) {
	home := t.TempDir()
	cfg := config.Config{APIBaseURL: "http://127.0.0.1:1", ElysianHome: home}
	payload := `{"lastUserInput":"We ship from release/2026 on Fridays.","conversationId":"c9"}`
	var out bytes.Buffer
	if err := Run(context.Background(), cfg, "agy", Prompt, strings.NewReader(payload), &out); err == nil {
		t.Fatal("an unreachable API must be an error")
	}
	api, live := serve(t, home)
	if got := run(t, live, "agy", Prompt, payload); got == "" || len(api.saved) != 1 {
		t.Fatalf("the retry must run, got %q and %d saves", got, len(api.saved))
	}
	text, _ := capturable(`config {"api_key": "abcd1234efgh5678", "client_secret":"zyxw9876vuts5432"}`)
	if strings.Contains(text, "abcd1234") || strings.Contains(text, "zyxw9876") {
		t.Fatalf("got %q", text)
	}
}

func TestReviewRoundOneFindings(t *testing.T) {
	t.Run("prefixed environment names and JSON keys are masked", func(t *testing.T) {
		text, _ := capturable(`run with ELYSIAN_AUTH_TOKEN=abcd1234efgh AWS_SECRET_ACCESS_KEY=wxyz98765432 {"password":"correct horse, battery"} passwd=hunt,er2 api_key: 'short'`)
		for _, secret := range []string{"abcd1234efgh", "wxyz98765432", "horse", "battery", "er2", "short"} {
			if strings.Contains(text, secret) {
				t.Fatalf("%s leaked in %q", secret, text)
			}
		}
	})
	t.Run("a prompt refuses an API that serves another store", func(t *testing.T) {
		api, cfg := serve(t, t.TempDir())
		api.served = "/somewhere/else"
		var out bytes.Buffer
		err := Run(context.Background(), cfg, "claude", Prompt, strings.NewReader("{"+statement+"}"), &out)
		if err == nil || !strings.Contains(err.Error(), "serves /somewhere/else") || len(api.saved) != 0 {
			t.Fatalf("got %v and %d saves", err, len(api.saved))
		}
	})
	t.Run("a prompt another hook holds waits for it and is not run twice", func(t *testing.T) {
		home := t.TempDir()
		api, cfg := serve(t, home)
		in := Input{Prompt: "We ship from release/2026 on Fridays.", SessionID: "c1"}
		holder := &marker{home: home, purpose: "prompt", client: "agy", session: in.SessionID, value: in.Prompt}
		if claimed, err := holder.claim(context.Background()); err != nil || !claimed {
			t.Fatalf("got %v %v", claimed, err)
		}
		payload := `{"lastUserInput":"We ship from release/2026 on Fridays.","conversationId":"c1"}`
		finished := make(chan string)
		go func() {
			var out bytes.Buffer
			Run(context.Background(), cfg, "agy", Prompt, strings.NewReader(payload), &out)
			finished <- out.String()
		}()
		time.Sleep(200 * time.Millisecond)
		holder.mark()
		holder.release()
		if out := <-finished; out != "" || api.searches != 0 {
			t.Fatalf("a prompt the holder finished must not run again, got %q after %d searches", out, api.searches)
		}
	})
	t.Run("kimi opens the session before it saves the first prompt", func(t *testing.T) {
		api, cfg := serve(t, t.TempDir())
		run(t, cfg, "kimi", Prompt, `{"prompt":"We ship from release/2026 every Friday.","session_id":"k2","cwd":"/tmp/demo"}`)
		if strings.Join(api.order, ",") != "search,search,save" {
			t.Fatalf("got %v", api.order)
		}
	})
}

func TestAClaimTakenAfterTheHolderFinishedIsDropped(t *testing.T) {
	home := t.TempDir()
	m := &marker{home: home, purpose: "prompt", client: "agy", session: "c1", value: "We ship on Fridays."}
	if err := m.mark(); err != nil {
		t.Fatal(err)
	}
	if claimed, err := m.claim(context.Background()); err != nil || claimed || m.lock != nil {
		t.Fatalf("a finished prompt must not be claimed nor its lock kept, got %v %v", claimed, err)
	}
}

func TestFiftyHooksFiredTogetherHandleOnePromptOnce(t *testing.T) {
	home := t.TempDir()
	var wg sync.WaitGroup
	var mu sync.Mutex
	handled := 0
	for range 50 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			m := &marker{home: home, purpose: "prompt", client: "agy", session: "c1", value: "We ship on Fridays."}
			claimed, err := m.claim(context.Background())
			if err != nil || !claimed {
				return
			}
			defer m.release()
			mu.Lock()
			handled++
			mu.Unlock()
			m.mark()
		}()
	}
	wg.Wait()
	if handled != 1 {
		t.Fatalf("one prompt was handled %d times", handled)
	}
}

func TestQuotedPasswordsAreMaskedWhole(t *testing.T) {
	for _, prompt := range []string{`{"password":"correct horse battery staple"}`, `{"password":"abcd1234,efgh5678"}`, `{"password":"prefix\"SYNTHETIC_PRIVATE_TAIL"}`} {
		text, _ := capturable("save this config " + prompt)
		for _, part := range []string{"horse", "staple", "abcd1234", "efgh5678", "SYNTHETIC_PRIVATE_TAIL"} {
			if strings.Contains(text, part) {
				t.Fatalf("%q leaked from %q: %q", part, prompt, text)
			}
		}
	}
}

func TestAStuckHolderCostsThePromptOnlyItsBudget(t *testing.T) {
	home := t.TempDir()
	_, cfg := serve(t, home)
	holder := &marker{home: home, purpose: "prompt", client: "agy", session: "c3", value: "We ship from release/2026 on Fridays."}
	if claimed, err := holder.claim(context.Background()); err != nil || !claimed {
		t.Fatalf("got %v %v", claimed, err)
	}
	defer holder.release()
	started := time.Now()
	var out bytes.Buffer
	err := Run(context.Background(), cfg, "agy", Prompt, strings.NewReader(`{"lastUserInput":"We ship from release/2026 on Fridays.","conversationId":"c3"}`), &out)
	if err == nil || !strings.Contains(err.Error(), "still holds") || time.Since(started) > promptBudget+time.Second {
		t.Fatalf("got %v after %s", err, time.Since(started))
	}
}
