package mcpserver

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/ELY-Open-Source/Elysium/elysium-mcp/internal/apiclient"
)

// askingServer records the path and query string of every request so a test can
// prove the tool asked for the session it was given, not a guess built from it.
func askingServer(t *testing.T, body string, seen *[]string) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		*seen = append(*seen, r.URL.Path+"?"+r.URL.RawQuery)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(body))
	}))
}

func TestWorkingSetAsksForTheSessionAndKeepsWhatTheStoreSaw(t *testing.T) {
	var seen []string
	server := askingServer(t, `[
		{"atom_id":"mem-1:text","holder_id":"妻子","session_id":"cooking-2026-10","text":"钥匙在玄关抽屉","recall_count":3,"importance":null,"last_recalled_at":null},
		{"atom_id":"mem-2:text","holder_id":"妻子","session_id":"cooking-2026-10","text":"恒温器调到 24 度","recall_count":0,"importance":0.8,"last_recalled_at":"2026-10-09T04:00:00+00:00"}
	]`, &seen)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	_, out, err := s.workingSetTool(context.Background(), nil, WorkingSetInput{Holder: "妻子", Session: "cooking-2026-10"})
	if err != nil {
		t.Fatalf("working_set failed: %v", err)
	}
	if len(seen) != 1 || seen[0] != "/api/memory/working?holder=%E5%A6%BB%E5%AD%90&session=cooking-2026-10" {
		t.Fatalf("the tool asked %v, want the holder and session encoded on the query", seen)
	}
	if len(out.Atoms) != 2 || out.Atoms[0].Text != "钥匙在玄关抽屉" || out.Atoms[1].Text != "恒温器调到 24 度" {
		t.Fatalf("working set = %+v, want the store's order kept", out.Atoms)
	}
	if out.Atoms[0].SessionID != "cooking-2026-10" || out.Atoms[0].RecallCount != 3 {
		t.Errorf("a working set that drops the session id or the recall count is half-blind, got %+v", out.Atoms[0])
	}
	if out.Atoms[0].Importance != nil {
		t.Errorf("a null importance became %v, want it left unset", *out.Atoms[0].Importance)
	}
	if out.Atoms[1].Importance == nil || *out.Atoms[1].Importance != 0.8 {
		t.Errorf("importance = %v, want the stated 0.8", out.Atoms[1].Importance)
	}
}

func TestWorkingSetRefusesARequestWithoutASession(t *testing.T) {
	var seen []string
	server := askingServer(t, `[]`, &seen)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	if _, _, err := s.workingSetTool(context.Background(), nil, WorkingSetInput{Holder: "wife"}); err == nil {
		t.Fatal("a working set without a session was accepted, but a session is what makes it a working set")
	}
	if len(seen) != 0 {
		t.Errorf("the tool reached for the network with %v before refusing, want the request refused locally", seen)
	}
}

func TestMemoryConflictsNamesBothSidesOfTheDisagreement(t *testing.T) {
	var seen []string
	server := askingServer(t, `[
		{"conflict_id":7,"older_atom_id":"mem-1:text","newer_atom_id":"mem-2:text","holder_id":"wife","scenario":"home","terms":["恒温"],"older_value":"22","newer_value":"24","detected_at":"2026-10-09T04:00:00+00:00","resolved_at":null}
	]`, &seen)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	_, out, err := s.conflictsTool(context.Background(), nil, ConflictsInput{Holder: "wife"})
	if err != nil {
		t.Fatalf("memory_conflicts failed: %v", err)
	}
	if len(seen) != 1 || seen[0] != "/api/memory/conflicts?holder=wife" {
		t.Fatalf("the tool asked %v, want the holder on the query", seen)
	}
	if len(out.Conflicts) != 1 {
		t.Fatalf("conflicts = %+v, want the one unsettled pair", out.Conflicts)
	}
	record := out.Conflicts[0]
	if record.OlderAtomID == "" || record.NewerAtomID == "" || record.OlderValue != "22" || record.NewerValue != "24" {
		t.Errorf("conflict = %+v, want both sides and both values so the caller can pick one", record)
	}
	if len(record.Terms) != 1 || record.Terms[0] != "恒温" {
		t.Errorf("terms = %v, want the term the two memories disagree about", record.Terms)
	}
	if record.ResolvedAt != "" {
		t.Errorf("resolved_at = %q, want an unsettled conflict reading as unresolved", record.ResolvedAt)
	}
}

func TestMemoryConflictsWithoutAHolderAsksForEveryHolder(t *testing.T) {
	var seen []string
	server := askingServer(t, `[]`, &seen)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	if _, _, err := s.conflictsTool(context.Background(), nil, ConflictsInput{}); err != nil {
		t.Fatalf("memory_conflicts failed: %v", err)
	}
	if len(seen) != 1 || seen[0] != "/api/memory/conflicts?" {
		t.Fatalf("the tool asked %v, want no holder filter so the whole store is listed", seen)
	}
}
