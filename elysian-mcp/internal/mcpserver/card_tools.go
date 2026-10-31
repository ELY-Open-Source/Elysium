package mcpserver

import (
	"context"
	"strings"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/domain"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type CardInput struct {
	HolderID string `json:"holder_id,omitempty" jsonschema:"optional exact holder id; ask for that holder's card instead of the whole store's"`
}

type CardOutput struct {
	Card   *domain.CapabilityCard `json:"card,omitempty"`
	Holder *domain.HolderCard     `json:"holder,omitempty"`
}

// registerCardTools adds the read that needs no memory access at all: what this
// store can answer. A caller with a new batch of questions reads the card first
// instead of discovering the gaps one question at a time.
func (s *Server) registerCardTools(server *mcp.Server) {
	mcp.AddTool(server, &mcp.Tool{
		Name:        "elysian_card",
		Annotations: readOnly,
		Title:       "Capability card",
		Description: "What this store can answer, derived from what it holds: schema version, senses present, which holders exist and what they hold, and what is mounted. No memory text is shown, so it is safe to read before trusting the store.",
	}, s.cardTool)
}

func (s *Server) cardTool(ctx context.Context, _ *mcp.CallToolRequest, input CardInput) (*mcp.CallToolResult, CardOutput, error) {
	if strings.TrimSpace(input.HolderID) == "" {
		card, err := s.api.Card(ctx)
		if err != nil {
			return nil, CardOutput{}, err
		}
		return nil, CardOutput{Card: card}, nil
	}
	holder, err := s.api.HolderCard(ctx, input.HolderID)
	if err != nil {
		return nil, CardOutput{}, err
	}
	return nil, CardOutput{Holder: holder}, nil
}
