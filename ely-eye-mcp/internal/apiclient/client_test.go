package apiclient

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestPostSendsJSONAndDecodesTheAnswer(t *testing.T) {
	var gotPath string
	var gotBody map[string]any
	var gotType string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		gotType = r.Header.Get("Content-Type")
		body, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(body, &gotBody)
		w.WriteHeader(http.StatusCreated)
		_, _ = w.Write([]byte(`{"atom_id":"mem-1:text","holder_id":"wife"}`))
	}))
	defer server.Close()

	var out struct {
		AtomID   string `json:"atom_id"`
		HolderID string `json:"holder_id"`
	}
	client := New(server.URL)
	err := client.Post(context.Background(), "/api/memory", map[string]any{"text": "钥匙在玄关"}, &out)
	if err != nil {
		t.Fatalf("Post failed: %v", err)
	}
	if gotPath != "/api/memory" {
		t.Errorf("path = %q, want /api/memory", gotPath)
	}
	if gotType != "application/json" {
		t.Errorf("content type = %q, want application/json", gotType)
	}
	if gotBody["text"] != "钥匙在玄关" {
		t.Errorf("body = %v, want the statement to survive the trip", gotBody)
	}
	if out.AtomID != "mem-1:text" || out.HolderID != "wife" {
		t.Errorf("decoded = %+v, want the server's stamped atom", out)
	}
}

func TestRejectedWriteCarriesTheServersReason(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusUnprocessableEntity)
		_, _ = w.Write([]byte(`{"detail":"remember needs a holder; a memory nobody owns cannot be referred to"}`))
	}))
	defer server.Close()

	err := New(server.URL).Post(context.Background(), "/api/memory", map[string]any{}, &struct{}{})
	if err == nil {
		t.Fatal("a rejected write must not look like success")
	}
	if !strings.Contains(err.Error(), "remember needs a holder") {
		t.Errorf("error = %v, want the rule the caller broke", err)
	}
}

func TestUnreachableAPIPointsAtTheServerThatShouldBeRunning(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	url := server.URL
	server.Close()

	err := New(url).Post(context.Background(), "/api/memory", map[string]any{}, &struct{}{})
	if err == nil {
		t.Fatal("an unreachable API must fail")
	}
	if !strings.Contains(err.Error(), "ely-eye serve") {
		t.Errorf("error = %v, want the fix the operator can run", err)
	}
}

func TestTheWriteTokenRidesOnEveryRequest(t *testing.T) {
	seen := make(chan string, 2)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen <- r.Header.Get("Authorization")
		_, _ = w.Write([]byte(`{}`))
	}))
	defer server.Close()

	client := New(server.URL)
	client.Token = "sekret"
	if err := client.Post(context.Background(), "/api/memory", map[string]any{}, &struct{}{}); err != nil {
		t.Fatalf("Post failed: %v", err)
	}
	if err := client.Get(context.Background(), "/api/status", &struct{}{}); err != nil {
		t.Fatalf("Get failed: %v", err)
	}
	for _, path := range []string{"POST", "GET"} {
		if got := <-seen; got != "Bearer sekret" {
			t.Errorf("%s Authorization = %q, want the bearer token the server demands", path, got)
		}
	}
}

func TestNoTokenMeansNoHeader(t *testing.T) {
	seen := make(chan string, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen <- r.Header.Get("Authorization")
		_, _ = w.Write([]byte(`{}`))
	}))
	defer server.Close()

	if err := New(server.URL).Get(context.Background(), "/api/status", &struct{}{}); err != nil {
		t.Fatalf("Get failed: %v", err)
	}
	if got := <-seen; got != "" {
		t.Errorf("Authorization = %q, want no header when no token is configured", got)
	}
}

func TestTheTokenComesFromTheEnvironment(t *testing.T) {
	t.Setenv("ELY_EYE_AUTH_TOKEN", "  sekret  ")
	if got := New("http://127.0.0.1:8765").Token; got != "sekret" {
		t.Errorf("Token = %q, want the environment's value, trimmed", got)
	}
}

func TestNewDefaultsToLocalServe(t *testing.T) {
	if got := New("").BaseURL; got != "http://127.0.0.1:8765" {
		t.Errorf("BaseURL = %q, want the default serve address", got)
	}
	if got := New("http://127.0.0.1:9000/").BaseURL; got != "http://127.0.0.1:9000" {
		t.Errorf("BaseURL = %q, want the trailing slash trimmed", got)
	}
}
