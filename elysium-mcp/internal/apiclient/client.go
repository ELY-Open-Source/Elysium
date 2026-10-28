// Package apiclient talks to a running Elysium API server. The Python service
// owns every write rule, so the MCP server forwards mutations instead of
// duplicating them against SQLite.
package apiclient

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"git.zacharyzhang.com/ZacharyZhang-NY/ely-eye/elysium-mcp/internal/domain"
)

const maxErrorBody = 4096

type Client struct {
	BaseURL string
	Token   string
	HTTP    *http.Client
}

func New(baseURL string) *Client {
	if strings.TrimSpace(baseURL) == "" {
		baseURL = "http://127.0.0.1:8765"
	}
	return &Client{
		BaseURL: strings.TrimRight(baseURL, "/"),
		Token:   strings.TrimSpace(os.Getenv("ELYSIUM_AUTH_TOKEN")),
		HTTP:    &http.Client{Timeout: 30 * time.Second},
	}
}

// authorize attaches the write token; the server refuses a write without it.
func (c *Client) authorize(request *http.Request) {
	if c.Token != "" {
		request.Header.Set("Authorization", "Bearer "+c.Token)
	}
}

// Get fetches a JSON resource into out.
func (c *Client) Get(ctx context.Context, path string, out any) error {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, c.BaseURL+path, nil)
	if err != nil {
		return fmt.Errorf("cannot build the request for %s: %w", path, err)
	}
	c.authorize(request)
	return c.do(request, path, out)
}

func (c *Client) do(request *http.Request, path string, out any) error {
	response, err := c.HTTP.Do(request)
	if err != nil {
		return fmt.Errorf("the Elysium API at %s is unreachable; start it with `elysium serve`: %w", c.BaseURL, err)
	}
	defer response.Body.Close()

	data, err := io.ReadAll(io.LimitReader(response.Body, maxErrorBody))
	if err != nil {
		return fmt.Errorf("%s returned an unreadable body: %w", path, err)
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return errors.New(path + " was rejected: " + serverReason(response.StatusCode, data))
	}
	if out == nil {
		return nil
	}
	if err := json.Unmarshal(data, out); err != nil {
		return fmt.Errorf("%s returned JSON that does not decode: %w", path, err)
	}
	return nil
}

// Post sends body as JSON and decodes the response into out. A rejected request
// carries the server's own reason, which is the rule the caller broke.
func (c *Client) Post(ctx context.Context, path string, body any, out any) error {
	payload, err := json.Marshal(body)
	if err != nil {
		return fmt.Errorf("cannot encode the request for %s: %w", path, err)
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, c.BaseURL+path, bytes.NewReader(payload))
	if err != nil {
		return fmt.Errorf("cannot build the request for %s: %w", path, err)
	}
	request.Header.Set("Content-Type", "application/json")
	c.authorize(request)
	return c.do(request, path, out)
}

// serverReason prefers FastAPI's {"detail": "..."} so the caller sees the broken
// rule instead of an HTML error page.
func serverReason(status int, data []byte) string {
	var envelope struct {
		Detail string `json:"detail"`
	}
	if err := json.Unmarshal(data, &envelope); err == nil && strings.TrimSpace(envelope.Detail) != "" {
		return envelope.Detail
	}
	trimmed := strings.TrimSpace(string(data))
	if trimmed == "" {
		return fmt.Sprintf("HTTP %d with no reason", status)
	}
	return trimmed
}

// WorkingSet asks for what one session recorded, in the order it recorded it,
// with no ranking involved. The session is required: without one, every memory
// in the store would be working memory.
func (c *Client) WorkingSet(ctx context.Context, holder, session string) ([]domain.Memory, error) {
	if strings.TrimSpace(holder) == "" {
		return nil, errors.New("holder is required")
	}
	if strings.TrimSpace(session) == "" {
		return nil, errors.New("session is required")
	}
	path := "/api/memory/working?holder=" + url.QueryEscape(holder) + "&session=" + url.QueryEscape(session)
	var atoms []domain.Memory
	if err := c.Get(ctx, path, &atoms); err != nil {
		return nil, err
	}
	return atoms, nil
}

// Conflicts lists the disagreements the store noticed and nobody has settled.
// An empty holder asks for every holder's, which is what an operator reviewing
// the whole store wants.
func (c *Client) Conflicts(ctx context.Context, holder string) ([]domain.ConflictRecord, error) {
	path := "/api/memory/conflicts"
	if strings.TrimSpace(holder) != "" {
		path += "?holder=" + url.QueryEscape(holder)
	}
	var records []domain.ConflictRecord
	if err := c.Get(ctx, path, &records); err != nil {
		return nil, err
	}
	return records, nil
}

// SearchOptions is one ranked query. Empty optional fields are omitted, so the
// server's own defaults decide rather than a zero value invented here.
type SearchOptions struct {
	Query    string
	Modality string
	Holder   string
	Scenario string
	Limit    int
}

// SearchResult carries the server's own verdict: "no_match" is a claim about the
// corpus, an empty hit list is not.
type SearchResult struct {
	Status     string           `json:"status"`
	Hits       []domain.AtomHit `json:"hits"`
	NextCursor string           `json:"next_cursor"`
}

// Search asks the running server to rank. The ranking lives in one place, so an
// MCP hit cannot disagree with an HTTP or CLI hit for the same query.
func (c *Client) Search(ctx context.Context, options SearchOptions) (*SearchResult, error) {
	if strings.TrimSpace(options.Query) == "" {
		return nil, errors.New("query is required")
	}
	body := map[string]any{"query": options.Query}
	if options.Limit > 0 {
		body["top_k"] = options.Limit
	}
	filters := map[string]string{}
	for key, value := range map[string]string{
		"modality": options.Modality,
		"holder":   options.Holder,
		"scenario": options.Scenario,
	} {
		if value != "" {
			filters[key] = value
		}
	}
	if len(filters) > 0 {
		body["filters"] = filters
	}
	var result SearchResult
	if err := c.Post(ctx, "/api/search", body, &result); err != nil {
		return nil, err
	}
	return &result, nil
}

// Card asks what the store can answer: the schema its answers come out under, which
// senses its memory actually covers, and who is in the directory. It is served
// without a token, so a caller can decide whether to send questions at all.
func (c *Client) Card(ctx context.Context) (*domain.CapabilityCard, error) {
	var card domain.CapabilityCard
	if err := c.Get(ctx, "/api/card", &card); err != nil {
		return nil, err
	}
	return &card, nil
}

// HolderCard asks the same question about one holder. The server derives it from the
// memories that holder owns, so a card cannot promise a modality the store lacks.
func (c *Client) HolderCard(ctx context.Context, holderID string) (*domain.HolderCard, error) {
	if strings.TrimSpace(holderID) == "" {
		return nil, errors.New("holder_id is required")
	}
	var card domain.HolderCard
	if err := c.Get(ctx, "/api/card/"+url.PathEscape(holderID), &card); err != nil {
		return nil, err
	}
	return &card, nil
}
