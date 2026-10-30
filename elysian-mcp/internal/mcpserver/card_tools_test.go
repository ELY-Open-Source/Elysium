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

const storeCardBody = `{"schema_version":11,"atoms":3,"sources":3,"modalities":{"text":2,"image":1},
"has_audio":false,"holders":[{"holder_id":"wife","name":"小美","kind":"person","knows_about":["home"],
"contact":{"channel":"signal"},"memories":2,"modalities":{"text":2},"scenarios":["home"],
"newest_memory":"2026-05-01T12:00:00+00:00","registered":true,"token_issued":true}],"mounts":{"mounted":[],"scoped":false,"atoms_in_scope":0}}`

func cardServer(t *testing.T, seen *[]string) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		*seen = append(*seen, r.Method+" "+r.URL.Path)
		if r.URL.Path == "/api/card/nobody" {
			w.WriteHeader(http.StatusNotFound)
			_ = json.NewEncoder(w).Encode(map[string]string{"detail": "no holder 'nobody' has memories or a directory entry"})
			return
		}
		if r.URL.Path == "/api/card/wife" {
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"holder_id":"wife","name":"小美","kind":"person","knows_about":["home"],"contact":{},"memories":2,"modalities":{"text":2},"scenarios":["home"],"newest_memory":"2026-05-01T12:00:00+00:00","registered":true,"token_issued":true}`))
			return
		}
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(storeCardBody))
	}))
}

func TestCardAsksTheStoreAndKeepsTheAnswerDerived(t *testing.T) {
	var seen []string
	server := cardServer(t, &seen)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	_, out, err := s.cardTool(context.Background(), nil, CardInput{})
	if err != nil {
		t.Fatalf("card failed: %v", err)
	}
	if seen[0] != "GET /api/card" {
		t.Errorf("request = %q, want the store card endpoint", seen[0])
	}
	if out.Card == nil || out.Holder != nil {
		t.Fatalf("card = %+v holder = %+v, want the store card only", out.Card, out.Holder)
	}
	if out.Card.SchemaVersion != 11 || out.Card.Atoms != 3 || out.Card.HasAudio {
		t.Errorf("card = %+v, want the server's own schema, counts and senses", out.Card)
	}
	if len(out.Card.Holders) != 1 || out.Card.Holders[0].TokenIssued != true {
		t.Errorf("holders = %+v, want the directory carried through", out.Card.Holders)
	}
	if out.Card.Holders[0].Contact["channel"] != "signal" {
		t.Errorf("contact = %+v, want the contact a referrer needs", out.Card.Holders[0].Contact)
	}
}

func TestCardWithAHolderAsksForThatHolderAlone(t *testing.T) {
	var seen []string
	server := cardServer(t, &seen)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	_, out, err := s.cardTool(context.Background(), nil, CardInput{HolderID: "wife"})
	if err != nil {
		t.Fatalf("holder card failed: %v", err)
	}
	if seen[0] != "GET /api/card/wife" {
		t.Errorf("request = %q, want the one-holder endpoint", seen[0])
	}
	if out.Holder == nil || out.Card != nil {
		t.Fatalf("holder = %+v card = %+v, want the holder card only", out.Holder, out.Card)
	}
	if out.Holder.HolderID != "wife" || out.Holder.Memories != 2 {
		t.Errorf("holder card = %+v, want wife's own counts", out.Holder)
	}
}

func TestCardTreatsABlankHolderAsTheWholeStore(t *testing.T) {
	var seen []string
	server := cardServer(t, &seen)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	if _, _, err := s.cardTool(context.Background(), nil, CardInput{HolderID: "   "}); err != nil {
		t.Fatalf("blank holder failed: %v", err)
	}
	if seen[0] != "GET /api/card" {
		t.Errorf("request = %q, want the store card rather than a path of spaces", seen[0])
	}
}

func TestCardPassesOnTheServersReasonForAnUnknownHolder(t *testing.T) {
	var seen []string
	server := cardServer(t, &seen)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	_, _, err := s.cardTool(context.Background(), nil, CardInput{HolderID: "nobody"})
	if err == nil {
		t.Fatal("an unknown holder must not answer with an empty card")
	}
	if !strings.Contains(err.Error(), "nobody") || !strings.Contains(err.Error(), "/api/card/nobody") {
		t.Errorf("error = %q, want the endpoint and the id the server named", err)
	}
}

func TestHolderCardRefusesAnEmptyIdBeforeTheNetwork(t *testing.T) {
	var seen []string
	server := cardServer(t, &seen)
	defer server.Close()

	if _, err := apiclient.New(server.URL).HolderCard(context.Background(), ""); err == nil {
		t.Fatal("an empty holder id should be refused, not fetched")
	}
	if len(seen) != 0 {
		t.Errorf("requests = %v, want none", seen)
	}
}
