// Package apiclient talks to a running Ely-Eye API server. The Python service
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
	"os"
	"strings"
	"time"

	"github.com/ZacharyZhang-NY/ely-eye/ely-eye-mcp/internal/domain"
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
		Token:   strings.TrimSpace(os.Getenv("ELY_EYE_AUTH_TOKEN")),
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
		return fmt.Errorf("the Ely-Eye API at %s is unreachable; start it with `ely-eye serve`: %w", c.BaseURL, err)
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
