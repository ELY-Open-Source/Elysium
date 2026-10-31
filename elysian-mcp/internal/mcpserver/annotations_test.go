package mcpserver

import (
	"context"
	"testing"

	"github.com/modelcontextprotocol/go-sdk/mcp"
)

// Clients decide whether to ask by these hints, so each tool states what it really does to the store.
func TestEveryToolsHintsMatchWhatItDoes(t *testing.T) {
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
	want := map[string]string{
		"search_atoms": "recalls", "compile_context": "recalls", "ask": "recalls", "mount_cartridge": "additive",
		"remember": "destructive", "supersede_memory": "destructive", "forget_memory": "destructive",
		"switch_cartridge": "destructive", "unmount_cartridge": "destructive", "append_to_cartridge": "destructive",
	}
	for _, tool := range listed.Tools {
		hints := tool.Annotations
		if hints == nil || hints.OpenWorldHint == nil || *hints.OpenWorldHint {
			t.Fatalf("%s must say it reaches nothing outside the store, got %+v", tool.Name, hints)
		}
		kind := "readOnly"
		switch {
		case hints.ReadOnlyHint:
		case hints.DestructiveHint != nil && *hints.DestructiveHint:
			kind = "destructive"
		case hints.IdempotentHint:
			kind = "additive"
		default:
			kind = "recalls"
		}
		expected := want[tool.Name]
		if expected == "" {
			expected = "readOnly"
		}
		if kind != expected {
			t.Fatalf("%s is labelled %s, but it is %s", tool.Name, kind, expected)
		}
	}
}
