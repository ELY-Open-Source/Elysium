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
	"strings"
	"time"
)

const maxErrorBody = 4096

type Client struct {
	BaseURL string
	HTTP    *http.Client
}

func New(baseURL string) *Client {
	if strings.TrimSpace(baseURL) == "" {
		baseURL = "http://127.0.0.1:8765"
	}
	return &Client{
		BaseURL: strings.TrimRight(baseURL, "/"),
		HTTP:    &http.Client{Timeout: 30 * time.Second},
	}
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
