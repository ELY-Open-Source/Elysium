package mcpserver

import (
	"context"
	"errors"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/domain"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type WhoKnowsInput struct {
	Query    string `json:"query" jsonschema:"what the asker wants to know, in the asker's own words"`
	AsHolder string `json:"as_holder,omitempty" jsonschema:"who is asking; decides which memories may be shown"`
	Limit    int    `json:"limit,omitempty" jsonschema:"how many candidates to return, default 8"`
}

type AskInput struct {
	Question    string `json:"question" jsonschema:"the question to answer from memory"`
	AsHolder    string `json:"as_holder,omitempty" jsonschema:"who is asking; their own memory is checked first"`
	MaxHops     int    `json:"max_hops,omitempty" jsonschema:"how many holders besides the asker may be asked, default 3"`
	IncludeText bool   `json:"include_text,omitempty" jsonschema:"show the memory text when the asker may already read it"`
}

// registerDirectoryTools exposes the transactive surface: who knows, and ask-and-get-referred.
func (s *Server) registerDirectoryTools(server *mcp.Server) {
	mcp.AddTool(server, &mcp.Tool{
		Title:       "Who knows",
		Name:        "who_knows",
		Annotations: readOnly,
		Description: "Rank the holders whose memories answer a query, with the evidence and how to reach them. The directory counts memories the asker cannot read; that is the point. no_holder_knows is a result, not a failure.",
	}, s.whoKnows)

	mcp.AddTool(server, &mcp.Tool{
		Title:       "Ask and get referred",
		Name:        "ask",
		Annotations: readOnly,
		Description: "Ask the asker's own memory, then the directory. answered means somebody's memory matched; referred means the best holder's memory is private, so the answer is the pointer and contact, never the text.",
	}, s.askMemory)

	mcp.AddTool(server, &mcp.Tool{
		Title:       "List holders",
		Name:        "list_holders",
		Annotations: readOnly,
		Description: "List registered holders: the people, agents, and services a referral can walk to.",
	}, s.listHolders)
}

type whoKnowsOutput struct {
	Report domain.WhoKnowsReport `json:"report" jsonschema:"the ranked candidates and their evidence"`
}

type askOutput struct {
	Answer domain.ReferralAnswer `json:"answer" jsonschema:"who answered, who was asked, and what may be shown"`
}

type holdersOutput struct {
	Holders []domain.Holder `json:"holders" jsonschema:"the registered holders"`
}

func (s *Server) whoKnows(ctx context.Context, _ *mcp.CallToolRequest, in WhoKnowsInput) (*mcp.CallToolResult, whoKnowsOutput, error) {
	if in.Query == "" {
		return nil, whoKnowsOutput{}, errors.New("query is required")
	}
	var report domain.WhoKnowsReport
	body := map[string]any{"query": in.Query}
	if in.AsHolder != "" {
		body["as_holder"] = in.AsHolder
	}
	if in.Limit > 0 {
		body["limit"] = in.Limit
	}
	if err := s.api.Post(ctx, "/api/who_knows", body, &report); err != nil {
		return nil, whoKnowsOutput{}, err
	}
	return nil, whoKnowsOutput{Report: report}, nil
}

func (s *Server) askMemory(ctx context.Context, _ *mcp.CallToolRequest, in AskInput) (*mcp.CallToolResult, askOutput, error) {
	if in.Question == "" {
		return nil, askOutput{}, errors.New("question is required")
	}
	var answer domain.ReferralAnswer
	body := map[string]any{"question": in.Question}
	if in.AsHolder != "" {
		body["as_holder"] = in.AsHolder
	}
	if in.MaxHops > 0 {
		body["max_hops"] = in.MaxHops
	}
	if in.IncludeText {
		body["include_text"] = true
	}
	if err := s.api.Post(ctx, "/api/ask", body, &answer); err != nil {
		return nil, askOutput{}, err
	}
	return nil, askOutput{Answer: answer}, nil
}

func (s *Server) listHolders(ctx context.Context, _ *mcp.CallToolRequest, _ struct{}) (*mcp.CallToolResult, holdersOutput, error) {
	var holders []domain.Holder
	if err := s.api.Get(ctx, "/api/holders", &holders); err != nil {
		return nil, holdersOutput{}, err
	}
	return nil, holdersOutput{Holders: holders}, nil
}
