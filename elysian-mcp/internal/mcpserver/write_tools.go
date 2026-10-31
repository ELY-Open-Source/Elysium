package mcpserver

import (
	"context"
	"errors"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/domain"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type RememberInput struct {
	Text               string `json:"text" jsonschema:"the statement to remember, kept verbatim"`
	Scenario           string `json:"scenario,omitempty" jsonschema:"optional context label such as home or work"`
	Session            string `json:"session_id,omitempty" jsonschema:"the conversation this belongs to; working_set reloads a session in order"`
	EventTime          string `json:"event_time,omitempty" jsonschema:"when it was true, ISO 8601 with offset, e.g. 2026-05-01T12:00:00+08:00"`
	EventTimePrecision string `json:"event_time_precision,omitempty" jsonschema:"instant, minute, hour, day, month, or year; required with event_time"`
	RetentionUntil     string `json:"retention_until,omitempty" jsonschema:"ISO 8601 with offset; the memory stops being retrievable after this"`
}

type SupersedeInput struct {
	AtomID             string `json:"atom_id" jsonschema:"exact Evidence Atom id being replaced"`
	Text               string `json:"text" jsonschema:"the newer statement, kept verbatim"`
	Scenario           string `json:"scenario,omitempty" jsonschema:"optional context label such as home or work"`
	Session            string `json:"session_id,omitempty" jsonschema:"the conversation this belongs to; working_set reloads a session in order"`
	EventTime          string `json:"event_time,omitempty" jsonschema:"when the new statement became true, ISO 8601 with offset"`
	EventTimePrecision string `json:"event_time_precision,omitempty" jsonschema:"instant, minute, hour, day, month, or year; required with event_time"`
}

type ForgetInput struct {
	AtomID   string `json:"atom_id,omitempty" jsonschema:"exact Evidence Atom id to forget"`
	SourceID string `json:"source_id,omitempty" jsonschema:"exact source id to forget, removing every atom of that source"`
	Reason   string `json:"reason,omitempty" jsonschema:"why this memory is gone"`
}

type RememberOutput struct {
	Atom domain.Memory `json:"atom"`
}

type ForgetOutput struct {
	Report domain.ForgetReport `json:"report"`
}

func (s *Server) registerWriteTools(server *mcp.Server) {
	mcp.AddTool(server, &mcp.Tool{
		Name:        "remember",
		Annotations: destructive,
		Title:       "Remember",
		Description: "Store a new memory. The Elysian server stamps the holder, origin and ingestion time, so a caller cannot claim to be somebody else.",
	}, s.rememberTool)
	mcp.AddTool(server, &mcp.Tool{
		Name:        "supersede_memory",
		Annotations: destructive,
		Title:       "Supersede a memory",
		Description: "Replace a memory with a newer statement. The old one stops being retrievable but keeps its record, so the timeline stays readable.",
	}, s.supersedeTool)
	mcp.AddTool(server, &mcp.Tool{
		Name:        "forget_memory",
		Annotations: destructive,
		Title:       "Forget a memory",
		Description: "Delete a memory by atom_id or source_id and drop the derived indexes that would keep surfacing it.",
	}, s.forgetTool)
}

func (s *Server) rememberTool(ctx context.Context, _ *mcp.CallToolRequest, input RememberInput) (*mcp.CallToolResult, RememberOutput, error) {
	if input.Text == "" {
		return nil, RememberOutput{}, errors.New("text is required")
	}
	var atom domain.Memory
	if err := s.api.Post(ctx, "/api/memory", input, &atom); err != nil {
		return nil, RememberOutput{}, err
	}
	return nil, RememberOutput{Atom: atom}, nil
}

func (s *Server) supersedeTool(ctx context.Context, _ *mcp.CallToolRequest, input SupersedeInput) (*mcp.CallToolResult, RememberOutput, error) {
	if input.AtomID == "" {
		return nil, RememberOutput{}, errors.New("atom_id is required")
	}
	if input.Text == "" {
		return nil, RememberOutput{}, errors.New("text is required")
	}
	var atom domain.Memory
	if err := s.api.Post(ctx, "/api/memory/supersede", input, &atom); err != nil {
		return nil, RememberOutput{}, err
	}
	return nil, RememberOutput{Atom: atom}, nil
}

func (s *Server) forgetTool(ctx context.Context, _ *mcp.CallToolRequest, input ForgetInput) (*mcp.CallToolResult, ForgetOutput, error) {
	if (input.AtomID == "") == (input.SourceID == "") {
		return nil, ForgetOutput{}, errors.New("forget takes exactly one of atom_id or source_id")
	}
	var report domain.ForgetReport
	if err := s.api.Post(ctx, "/api/memory/forget", input, &report); err != nil {
		return nil, ForgetOutput{}, err
	}
	return nil, ForgetOutput{Report: report}, nil
}
