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

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/config"
)

// fakeAPI answers search with one stored memory and records every save and search.
type fakeAPI struct {
	mu       sync.Mutex
	saved    []map[string]any
	searches int
}

func serve(t *testing.T, home string) (*fakeAPI, config.Config) {
	t.Helper()
	api := &fakeAPI{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		api.mu.Lock()
		defer api.mu.Unlock()
		switch r.URL.Path {
		case "/api/status":
			json.NewEncoder(w).Encode(map[string]any{"data_home": home})
		case "/api/search":
			api.searches++
			json.NewEncoder(w).Encode(map[string]any{"status": "hits", "hits": []any{map[string]any{
				"atom": map[string]any{"text": "The release branch is release/2026.", "ingested_at": "2026-10-30T09:00:00Z", "scenario": "demo"}, "final_score": 1.0,
			}}})
		case "/api/memory":
			var body map[string]any
			json.NewDecoder(r.Body).Decode(&body)
			api.saved = append(api.saved, body)
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
	for _, skipped := range []string{"/compact", "!ls", "ok", "继续", "发布前要跑什么检查？", "what branch do we ship from?"} {
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
