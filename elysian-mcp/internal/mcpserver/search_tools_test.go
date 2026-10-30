package mcpserver

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/apiclient"
)

func searchTestServer(t *testing.T, recorded *map[string]any) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/search" {
			t.Errorf("path = %q, want /api/search", r.URL.Path)
		}
		var body map[string]any
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("request body does not decode: %v", err)
		}
		*recorded = body
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"query": "钥匙",
			"status": "hits",
			"hits": [{"atom": {"atom_id": "mem-1:text", "source_id": "mem-1", "modality": "text",
				"source": "memory://wife/home", "ingested_at": "2026-05-01T12:00:00+00:00",
				"holder_id": "wife", "scenario": "home", "text": "钥匙在玄关抽屉"},
				"sparse_score": 4.2, "dense_score": 0.0, "final_score": 0.016}],
			"next_cursor": null
		}`))
	}))
}

func TestSearchAsksTheServerToRank(t *testing.T) {
	var recorded map[string]any
	server := searchTestServer(t, &recorded)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	_, out, err := s.searchAtomsTool(context.Background(), nil, SearchAtomsInput{
		Query:    "钥匙",
		Modality: "text",
		Holder:   "wife",
		Scenario: "home",
		Limit:    5,
	})
	if err != nil {
		t.Fatalf("searchAtomsTool: %v", err)
	}
	if len(out.Hits) != 1 || out.Hits[0].Atom.AtomID != "mem-1:text" {
		t.Fatalf("hits = %+v, want the server's single hit", out.Hits)
	}
	if recorded["query"] != "钥匙" {
		t.Errorf("query sent = %v, want 钥匙", recorded["query"])
	}
	if recorded["top_k"] != float64(5) {
		t.Errorf("top_k sent = %v, want 5", recorded["top_k"])
	}
	filters, ok := recorded["filters"].(map[string]any)
	if !ok {
		t.Fatalf("filters sent = %v, want an object", recorded["filters"])
	}
	for key, want := range map[string]string{"modality": "text", "holder": "wife", "scenario": "home"} {
		if filters[key] != want {
			t.Errorf("filters[%s] = %v, want %q", key, filters[key], want)
		}
	}
}

func TestSearchRefusesAnEmptyQueryBeforeTheNetwork(t *testing.T) {
	var recorded map[string]any
	server := searchTestServer(t, &recorded)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	_, _, err := s.searchAtomsTool(context.Background(), nil, SearchAtomsInput{Query: "  "})
	if err == nil {
		t.Fatal("an empty query reached the server; the tool should refuse it")
	}
	if recorded != nil {
		t.Errorf("the server was called for an empty query: %v", recorded)
	}
}

func TestCompileContextPacksWhatTheServerReturned(t *testing.T) {
	var recorded map[string]any
	server := searchTestServer(t, &recorded)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	_, out, err := s.compileContextTool(context.Background(), nil, CompileContextInput{
		Question: "钥匙在哪",
		Profile:  "library_100m",
		Limit:    5,
	})
	if err != nil {
		t.Fatalf("compileContextTool: %v", err)
	}
	if out.Context.CacheTraceID == "" {
		t.Error("the packed context has no cache trace id")
	}
	if !strings.Contains(out.Context.PackedText, "钥匙在玄关抽屉") {
		t.Errorf("packed text does not carry the evidence: %q", out.Context.PackedText)
	}
}
