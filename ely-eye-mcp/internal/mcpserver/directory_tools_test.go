package mcpserver

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ZacharyZhang-NY/ely-eye/ely-eye-mcp/internal/apiclient"
)

func directoryServer(t *testing.T, body string, seen *[]string) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		payload, _ := io.ReadAll(r.Body)
		*seen = append(*seen, r.Method+" "+r.URL.Path+" "+string(payload))
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(body))
	}))
}

func TestWhoKnowsNamesTheHolderAndKeepsTheEvidence(t *testing.T) {
	var seen []string
	server := directoryServer(t, `{"query":"钥匙","as_holder":"husband","status":"found","hits":[{
		"holder_id":"wife","name":"小美","confidence":0.91,"matched":2,"top_score":0.02,
		"basis":["wife holds 2 matching memories the asker may not read"],"contact":{"channel":"signal"}}]}`, &seen)
	defer server.Close()

	_, out, err := (&Server{api: apiclient.New(server.URL)}).whoKnows(
		context.Background(), nil, WhoKnowsInput{Query: "钥匙", AsHolder: "husband"})
	if err != nil {
		t.Fatalf("who_knows failed: %v", err)
	}
	if out.Report.Status != "found" || len(out.Report.Hits) != 1 {
		t.Fatalf("report = %+v, want one found candidate", out.Report)
	}
	hit := out.Report.Hits[0]
	if hit.HolderID != "wife" || hit.Confidence != 0.91 || hit.Contact["channel"] != "signal" {
		t.Errorf("hit = %+v, want the holder, her confidence, and how to reach her", hit)
	}
	if len(seen) != 1 || !strings.Contains(seen[0], "POST /api/who_knows") || !strings.Contains(seen[0], `"query":"钥匙"`) {
		t.Fatalf("requests = %v, want one POST carrying the query", seen)
	}
}

func TestWhoKnowsRefusesAnEmptyQueryBeforeTheNetwork(t *testing.T) {
	var seen []string
	server := directoryServer(t, `{}`, &seen)
	defer server.Close()

	if _, _, err := (&Server{api: apiclient.New(server.URL)}).whoKnows(context.Background(), nil, WhoKnowsInput{}); err == nil {
		t.Fatal("an empty query must not reach the directory")
	}
	if len(seen) != 0 {
		t.Errorf("requests = %v, want none", seen)
	}
}

func TestAskReturnsThePointerAndNotThePrivateText(t *testing.T) {
	var seen []string
	server := directoryServer(t, `{"question":"钥匙在哪里","as_holder":"husband","status":"referred",
		"answered_by":"wife","asked":["husband","wife"],"hops":1,"atom_ids":[],"basis":["wife holds 1 matching memories the asker may not read"]}`, &seen)
	defer server.Close()

	_, out, err := (&Server{api: apiclient.New(server.URL)}).askMemory(
		context.Background(), nil, AskInput{Question: "钥匙在哪里", AsHolder: "husband", MaxHops: 2})
	if err != nil {
		t.Fatalf("ask failed: %v", err)
	}
	if out.Answer.Status != "referred" || out.Answer.Answer != "" {
		t.Errorf("answer = %+v, want a referral with no text", out.Answer)
	}
	if out.Answer.AnsweredBy != "wife" || out.Answer.Hops != 1 {
		t.Errorf("answer = %+v, want wife at hop 1", out.Answer)
	}
	if !strings.Contains(seen[0], `"max_hops":2`) || !strings.Contains(seen[0], `"as_holder":"husband"`) {
		t.Errorf("request = %s, want the hop budget and the asker", seen[0])
	}
}

func TestAskWithoutAnAskerOmitsTheIdentity(t *testing.T) {
	var seen []string
	server := directoryServer(t, `{"question":"garage code","status":"no_holder_knows","asked":[],"hops":0}`, &seen)
	defer server.Close()

	if _, _, err := (&Server{api: apiclient.New(server.URL)}).askMemory(context.Background(), nil, AskInput{Question: "garage code"}); err != nil {
		t.Fatalf("ask failed: %v", err)
	}
	var body map[string]any
	parts := strings.SplitN(seen[0], " ", 3)
	if err := json.Unmarshal([]byte(parts[2]), &body); err != nil {
		t.Fatalf("request body is not JSON: %s", seen[0])
	}
	if _, present := body["as_holder"]; present {
		t.Errorf("body = %v, want as_holder omitted so the server applies its own default", body)
	}
	if _, present := body["max_hops"]; present {
		t.Errorf("body = %v, want max_hops omitted; a Go zero is not a hop budget", body)
	}
}

func TestAskRefusesAnEmptyQuestion(t *testing.T) {
	var seen []string
	server := directoryServer(t, `{}`, &seen)
	defer server.Close()

	if _, _, err := (&Server{api: apiclient.New(server.URL)}).askMemory(context.Background(), nil, AskInput{}); err == nil {
		t.Fatal("an empty question must not be asked")
	}
	if len(seen) != 0 {
		t.Errorf("requests = %v, want none", seen)
	}
}

func TestListHoldersReadsTheRegistry(t *testing.T) {
	var seen []string
	server := directoryServer(t, `[{"holder_id":"wife","name":"小美","kind":"person","knows_about":["家里的钥匙"],"contact":{"channel":"signal"},"created_at":"2026-05-01T00:00:00+00:00","updated_at":"2026-05-01T00:00:00+00:00"}]`, &seen)
	defer server.Close()

	_, out, err := (&Server{api: apiclient.New(server.URL)}).listHolders(context.Background(), nil, struct{}{})
	if err != nil {
		t.Fatalf("list_holders failed: %v", err)
	}
	if len(out.Holders) != 1 || out.Holders[0].KnowsAbout[0] != "家里的钥匙" {
		t.Fatalf("holders = %+v, want the declared topics", out.Holders)
	}
	if len(seen) != 1 || !strings.HasPrefix(seen[0], "GET /api/holders") {
		t.Errorf("requests = %v, want one GET", seen)
	}
}
