package mcpserver

import (
	"context"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/domain"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type WorkingSetInput struct {
	Holder  string `json:"holder" jsonschema:"whose session this is"`
	Session string `json:"session" jsonschema:"the session whose memories to load, in the order they were recorded"`
}

type ConflictsInput struct {
	Holder string `json:"holder,omitempty" jsonschema:"limit the list to one holder; empty lists every disagreement in the store"`
}

type WorkingSetOutput struct {
	Atoms []domain.Memory `json:"atoms"`
}

type ConflictsOutput struct {
	Conflicts []domain.ConflictRecord `json:"conflicts"`
}

// registerTierTools exposes the two reads a session needs: what it already
// recorded, and what the store has not reconciled yet. Curation stays on the
// operator's CLI, because an agent should not decide what its own past is worth.
func (s *Server) registerTierTools(server *mcp.Server) {
	mcp.AddTool(server, &mcp.Tool{
		Name:        "working_set",
		Title:       "Load a session's working memory",
		Description: "Return everything one holder recorded in one session, oldest first, with no ranking involved. Use it to resume a conversation rather than to search it.",
	}, s.workingSetTool)
	mcp.AddTool(server, &mcp.Tool{
		Name:        "memory_conflicts",
		Title:       "List unsettled memory conflicts",
		Description: "Return disagreements the store noticed between two memories and nobody has settled. While one stands, a search answers with the newer side and hides the older one.",
	}, s.conflictsTool)
}

func (s *Server) workingSetTool(ctx context.Context, _ *mcp.CallToolRequest, input WorkingSetInput) (*mcp.CallToolResult, WorkingSetOutput, error) {
	atoms, err := s.api.WorkingSet(ctx, input.Holder, input.Session)
	if err != nil {
		return nil, WorkingSetOutput{}, err
	}
	return nil, WorkingSetOutput{Atoms: atoms}, nil
}

func (s *Server) conflictsTool(ctx context.Context, _ *mcp.CallToolRequest, input ConflictsInput) (*mcp.CallToolResult, ConflictsOutput, error) {
	records, err := s.api.Conflicts(ctx, input.Holder)
	if err != nil {
		return nil, ConflictsOutput{}, err
	}
	return nil, ConflictsOutput{Conflicts: records}, nil
}
