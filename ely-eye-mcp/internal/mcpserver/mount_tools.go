package mcpserver

import (
	"context"
	"errors"

	"git.zacharyzhang.com/ZacharyZhang-NY/ely-eye/ely-eye-mcp/internal/domain"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type CartridgeIDInput struct {
	CartridgeID string `json:"cartridge_id" jsonschema:"exact cartridge id"`
}

type AppendInput struct {
	CartridgeID string   `json:"cartridge_id" jsonschema:"exact cartridge id"`
	AtomIDs     []string `json:"atom_ids" jsonschema:"atom ids to add to this cartridge"`
}

type MountOutput struct {
	Manifest domain.CartridgeManifest `json:"manifest"`
}

type MountStateOutput struct {
	State domain.MountState `json:"state"`
}

// registerMountTools exposes the cartridge as a retrieval scope: the point of a
// cartridge is that the model stops hunting the whole library and asks one cartridge.
func (s *Server) registerMountTools(server *mcp.Server) {
	mcp.AddTool(server, &mcp.Tool{
		Name:        "mounted_cartridges",
		Title:       "Mounted cartridges",
		Description: "Report which cartridges are mounted. A mounted cartridge narrows every later search; nothing mounted means the whole library is searchable.",
	}, s.mountsTool)
	mcp.AddTool(server, &mcp.Tool{
		Name:        "mount_cartridge",
		Title:       "Mount a cartridge",
		Description: "Add one cartridge to the mounted set. The server refuses a cartridge whose KV fingerprint does not match this machine, because mismatched RoPE or quantization settings attend to wrong positions instead of failing.",
	}, s.mountTool)
	mcp.AddTool(server, &mcp.Tool{
		Name:        "switch_cartridge",
		Title:       "Switch to one cartridge",
		Description: "Mount one cartridge and nothing else.",
	}, s.switchTool)
	mcp.AddTool(server, &mcp.Tool{
		Name:        "unmount_cartridge",
		Title:       "Unmount a cartridge",
		Description: "Remove one cartridge from the mounted set and report what is left.",
	}, s.unmountTool)
	mcp.AddTool(server, &mcp.Tool{
		Name:        "append_to_cartridge",
		Title:       "Append memories to a cartridge",
		Description: "Add atoms to an existing cartridge. The bundle and its DNA are rewritten, so the cartridge id keeps describing the bytes it holds.",
	}, s.appendTool)
}

func (s *Server) mountsTool(ctx context.Context, _ *mcp.CallToolRequest, _ struct{}) (*mcp.CallToolResult, MountStateOutput, error) {
	var state domain.MountState
	if err := s.api.Get(ctx, "/api/mounts", &state); err != nil {
		return nil, MountStateOutput{}, err
	}
	return nil, MountStateOutput{State: state}, nil
}

func (s *Server) mountTool(ctx context.Context, _ *mcp.CallToolRequest, input CartridgeIDInput) (*mcp.CallToolResult, MountOutput, error) {
	if input.CartridgeID == "" {
		return nil, MountOutput{}, errors.New("cartridge_id is required")
	}
	var manifest domain.CartridgeManifest
	if err := s.api.Post(ctx, "/api/cartridges/"+input.CartridgeID+"/mount", struct{}{}, &manifest); err != nil {
		return nil, MountOutput{}, err
	}
	return nil, MountOutput{Manifest: manifest}, nil
}

func (s *Server) switchTool(ctx context.Context, _ *mcp.CallToolRequest, input CartridgeIDInput) (*mcp.CallToolResult, MountOutput, error) {
	if input.CartridgeID == "" {
		return nil, MountOutput{}, errors.New("cartridge_id is required")
	}
	var manifest domain.CartridgeManifest
	if err := s.api.Post(ctx, "/api/cartridges/"+input.CartridgeID+"/switch", struct{}{}, &manifest); err != nil {
		return nil, MountOutput{}, err
	}
	return nil, MountOutput{Manifest: manifest}, nil
}

func (s *Server) unmountTool(ctx context.Context, _ *mcp.CallToolRequest, input CartridgeIDInput) (*mcp.CallToolResult, MountStateOutput, error) {
	if input.CartridgeID == "" {
		return nil, MountStateOutput{}, errors.New("cartridge_id is required")
	}
	var state domain.MountState
	if err := s.api.Post(ctx, "/api/cartridges/"+input.CartridgeID+"/unmount", struct{}{}, &state); err != nil {
		return nil, MountStateOutput{}, err
	}
	return nil, MountStateOutput{State: state}, nil
}

func (s *Server) appendTool(ctx context.Context, _ *mcp.CallToolRequest, input AppendInput) (*mcp.CallToolResult, MountOutput, error) {
	if input.CartridgeID == "" {
		return nil, MountOutput{}, errors.New("cartridge_id is required")
	}
	if len(input.AtomIDs) == 0 {
		return nil, MountOutput{}, errors.New("atom_ids needs at least one atom")
	}
	var manifest domain.CartridgeManifest
	if err := s.api.Post(ctx, "/api/cartridges/"+input.CartridgeID+"/append", input, &manifest); err != nil {
		return nil, MountOutput{}, err
	}
	return nil, MountOutput{Manifest: manifest}, nil
}
