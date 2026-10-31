package mcpserver

import (
	"context"
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// Clients auto-approve by these hints (Codex `auto`, Droid risk levels), so every tool must carry them
// and only forget_memory may claim to destroy anything.
func TestEveryToolCarriesHintsAndOnlyForgetIsDestructive(t *testing.T) {
	ctx := context.Background()
	server := &Server{}
	mcpServer := mcp.NewServer(&mcp.Implementation{Name: "elysian", Version: "test"}, nil)
	server.registerTools(mcpServer)
	server.registerWriteTools(mcpServer)
	server.registerDirectoryTools(mcpServer)
	server.registerMountTools(mcpServer)
	server.registerTierTools(mcpServer)
	server.registerCardTools(mcpServer)
	serverSide, clientSide := mcp.NewInMemoryTransports()
	if _, err := mcpServer.Connect(ctx, serverSide, nil); err != nil {
		t.Fatal(err)
	}
	session, err := mcp.NewClient(&mcp.Implementation{Name: "probe", Version: "test"}, nil).Connect(ctx, clientSide, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer session.Close()
	listed, err := session.ListTools(ctx, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(listed.Tools) != 23 {
		t.Fatalf("expected 23 tools, got %d", len(listed.Tools))
	}
	for _, tool := range listed.Tools {
		hints := tool.Annotations
		if hints == nil || hints.OpenWorldHint == nil || *hints.OpenWorldHint {
			t.Fatalf("%s must say it reaches nothing outside the store, got %+v", tool.Name, hints)
		}
		destroys := hints.DestructiveHint != nil && *hints.DestructiveHint
		if destroys != (tool.Name == "forget_memory") {
			t.Fatalf("%s destructive=%v; only forget_memory destroys", tool.Name, destroys)
		}
		if !hints.ReadOnlyHint && hints.DestructiveHint == nil {
			t.Fatalf("%s writes, so it must state whether it destroys", tool.Name)
		}
	}
}
