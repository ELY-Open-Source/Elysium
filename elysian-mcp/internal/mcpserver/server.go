package mcpserver

import (
	"context"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/apiclient"
	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/config"
	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/store"
	"github.com/modelcontextprotocol/go-sdk/mcp"
)

type Server struct {
	cfg     config.Config
	store   *store.Store
	api     *apiclient.Client
	version string
}

func Run(ctx context.Context, cfg config.Config, version string) error {
	db, err := store.Open(ctx, cfg)
	if err != nil {
		return err
	}
	defer db.Close()
	api := apiclient.New(cfg.APIBaseURL)
	api.Token = cfg.Token
	server := &Server{cfg: cfg, store: db, api: api, version: version}
	mcpServer := mcp.NewServer(&mcp.Implementation{
		Name:    "elysian",
		Title:   "Elysian Context Cartridge MCP",
		Version: version,
	}, &mcp.ServerOptions{
		Instructions: "Use Elysian tools to retrieve local cartridge context, evidence atoms, proof suites, and compiled evidence packs. Read tools mirror local Elysian state without writing. remember, supersede_memory and forget_memory mutate memory through the Elysian API, which this server starts when it is down; the server, not the caller, decides who owns a memory. mount_cartridge and switch_cartridge decide what a search may see: mount a cartridge to ask only that cartridge, and unmount everything to ask the whole library. working_set reloads what one session already recorded, in order, without searching; memory_conflicts reports what the store has not reconciled, and settling one is the operator's act, not a tool's. elysian_card says what the store can answer before anything is sent: schema version, which senses its memory covers, and who holds what. A read with no operator token (ELYSIAN_AUTH_TOKEN or the one `elysian init` wrote) sees only memories nobody owns and memories marked for everyone.",
	})
	server.registerTools(mcpServer)
	server.registerWriteTools(mcpServer)
	server.registerDirectoryTools(mcpServer)
	server.registerMountTools(mcpServer)
	server.registerTierTools(mcpServer)
	server.registerCardTools(mcpServer)
	server.registerResources(mcpServer)
	if err := mcpServer.Run(ctx, &mcp.StdioTransport{}); err != nil {
		if errors.Is(err, io.EOF) || strings.HasSuffix(err.Error(), "EOF") {
			return nil
		}
		return err
	}
	return nil
}

func (s *Server) registerResources(server *mcp.Server) {
	addFileResource(server, "elysian://project/prd", "Elysian PRD", filepath.Join(s.cfg.ProjectRoot, "PRD.md"))
	addFileResource(server, "elysian://project/readme", "Elysian README", filepath.Join(s.cfg.ProjectRoot, "README.md"))
	addFileResource(server, "elysian://project/mcp-research", "Elysian MCP research notes", filepath.Join(s.cfg.ProjectRoot, "elysian-mcp", "docs", "RESEARCH.md"))
}

// addFileResource registers a project document only when it exists on disk.
// External deployments rarely ship the Elysian repository documents, so a
// missing file is a normal condition and the resource is simply omitted.
func addFileResource(server *mcp.Server, uri string, name string, path string) {
	info, err := os.Stat(path)
	if err != nil {
		return
	}
	size := info.Size()
	server.AddResource(&mcp.Resource{
		URI:         uri,
		Name:        name,
		Title:       name,
		Description: "Local Elysian project resource: " + path,
		MIMEType:    "text/markdown",
		Size:        size,
	}, func(ctx context.Context, request *mcp.ReadResourceRequest) (*mcp.ReadResourceResult, error) {
		_ = ctx
		data, err := os.ReadFile(path)
		if err != nil {
			return nil, err
		}
		return &mcp.ReadResourceResult{
			Contents: []*mcp.ResourceContents{{
				URI:      request.Params.URI,
				MIMEType: "text/markdown",
				Text:     string(data),
			}},
		}, nil
	})
}
