package mcpserver

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/apiclient"
)

func recordingServer(t *testing.T, status int, body string, seen *[]string) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		payload, _ := io.ReadAll(r.Body)
		var decoded map[string]any
		_ = json.Unmarshal(payload, &decoded)
		*seen = append(*seen, r.URL.Path+" "+string(payload)+" "+func() string {
			if decoded["text"] == nil {
				return "<no text>"
			}
			return decoded["text"].(string)
		}())
		w.WriteHeader(status)
		_, _ = w.Write([]byte(body))
	}))
}

func TestRememberSendsTheStatementAndReturnsTheStampedMemory(t *testing.T) {
	var seen []string
	server := recordingServer(t, http.StatusCreated,
		`{"atom_id":"mem-1:text","source_id":"mem-1","holder_id":"husband","origin":"self","text":"钥匙在玄关抽屉"}`, &seen)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	_, out, err := s.rememberTool(context.Background(), nil, RememberInput{Text: "钥匙在玄关抽屉", Scenario: "home"})
	if err != nil {
		t.Fatalf("remember failed: %v", err)
	}
	if out.Atom.HolderID != "husband" || out.Atom.Origin != "self" {
		t.Errorf("stamped memory = %+v, want the server's holder and origin", out.Atom)
	}
	if len(seen) != 1 || !strings.Contains(seen[0], "/api/memory") {
		t.Fatalf("requests = %v, want one POST to /api/memory", seen)
	}
	if !strings.Contains(seen[0], "钥匙在玄关抽屉") {
		t.Errorf("request = %s, want the statement verbatim", seen[0])
	}
}

func TestRememberRefusesAnEmptyStatement(t *testing.T) {
	var seen []string
	server := recordingServer(t, http.StatusCreated, `{}`, &seen)
	defer server.Close()

	if _, _, err := (&Server{api: apiclient.New(server.URL)}).rememberTool(context.Background(), nil, RememberInput{}); err == nil {
		t.Fatal("an empty memory must not be stored")
	}
	if len(seen) != 0 {
		t.Errorf("requests = %v, want the empty write rejected before the network", seen)
	}
}

func TestSupersedeNamesTheAtomItReplaces(t *testing.T) {
	var seen []string
	server := recordingServer(t, http.StatusOK,
		`{"atom_id":"mem-2:text","supersedes":["mem-1:text"],"valid_from":"2026-05-02T00:00:00+00:00"}`, &seen)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	_, out, err := s.supersedeTool(context.Background(), nil, SupersedeInput{AtomID: "mem-1:text", Text: "钥匙在客厅茶几"})
	if err != nil {
		t.Fatalf("supersede failed: %v", err)
	}
	if len(out.Atom.Supersedes) != 1 || out.Atom.Supersedes[0] != "mem-1:text" {
		t.Errorf("supersedes = %v, want the replaced atom", out.Atom.Supersedes)
	}
	if !strings.Contains(seen[0], "/api/memory/supersede") {
		t.Errorf("request = %s, want the supersede route", seen[0])
	}
}

func TestSupersedeRefusesAMissingAtomID(t *testing.T) {
	var seen []string
	server := recordingServer(t, http.StatusOK, `{}`, &seen)
	defer server.Close()

	if _, _, err := (&Server{api: apiclient.New(server.URL)}).supersedeTool(context.Background(), nil, SupersedeInput{Text: "新的说法"}); err == nil {
		t.Fatal("supersede must name the atom it replaces")
	}
	if len(seen) != 0 {
		t.Errorf("requests = %v, want no write attempted", seen)
	}
}

func TestForgetTakesExactlyOneID(t *testing.T) {
	var seen []string
	server := recordingServer(t, http.StatusOK, `{"source_id":"mem-1","atoms_deleted":1}`, &seen)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	for _, input := range []ForgetInput{{}, {AtomID: "a:text", SourceID: "b"}} {
		if _, _, err := s.forgetTool(context.Background(), nil, input); err == nil {
			t.Errorf("input %+v accepted, want exactly one id", input)
		}
	}
	_, out, err := s.forgetTool(context.Background(), nil, ForgetInput{SourceID: "mem-1", Reason: "moved house"})
	if err != nil {
		t.Fatalf("forget failed: %v", err)
	}
	if out.Report.AtomsDeleted != 1 {
		t.Errorf("report = %+v, want the deleted count back", out.Report)
	}
	if len(seen) != 1 || !strings.Contains(seen[0], "/api/memory/forget") {
		t.Errorf("requests = %v, want one POST to the forget route", seen)
	}
}

func TestARejectedWriteReachesTheCallerAsAnError(t *testing.T) {
	var seen []string
	server := recordingServer(t, http.StatusUnprocessableEntity,
		`{"detail":"mem-1:text was already closed"}`, &seen)
	defer server.Close()

	_, _, err := (&Server{api: apiclient.New(server.URL)}).supersedeTool(context.Background(), nil, SupersedeInput{AtomID: "mem-1:text", Text: "再说一次"})
	if err == nil {
		t.Fatal("a closed memory must not supersede silently")
	}
	if !strings.Contains(err.Error(), "already closed") {
		t.Errorf("error = %v, want the server's reason", err)
	}
}
