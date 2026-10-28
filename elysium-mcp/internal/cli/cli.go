package cli

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"

	"git.zacharyzhang.com/ZacharyZhang-NY/ely-eye/elysium-mcp/internal/config"
	"git.zacharyzhang.com/ZacharyZhang-NY/ely-eye/elysium-mcp/internal/mcpserver"
	"git.zacharyzhang.com/ZacharyZhang-NY/ely-eye/elysium-mcp/internal/setup"
	"git.zacharyzhang.com/ZacharyZhang-NY/ely-eye/elysium-mcp/internal/store"
)

// version is stamped at release build time via -ldflags -X. The default is the
// development version used by source builds.
var version = "0.1.0"

func Run(ctx context.Context, args []string) error {
	if len(args) == 0 {
		return errors.New(usage())
	}
	switch args[0] {
	case "server":
		return runServer(ctx, args[1:])
	case "setup":
		return runSetup(ctx, args[1:])
	case "status":
		return runStatus(ctx, args[1:])
	case "version":
		fmt.Println(version)
		return nil
	case "help", "-h", "--help":
		fmt.Print(usage())
		return nil
	default:
		return errors.New("unknown command: " + args[0])
	}
}

func runServer(ctx context.Context, args []string) error {
	flags := flag.NewFlagSet("server", flag.ContinueOnError)
	projectRoot := flags.String("project-root", "", "Elysium project root")
	elysiumHome := flags.String("elysium-home", "", "Elysium data home")
	flags.SetOutput(os.Stderr)
	if err := flags.Parse(args); err != nil {
		return err
	}
	cfg, err := config.Resolve(*projectRoot, *elysiumHome, "")
	if err != nil {
		return err
	}
	return mcpserver.Run(ctx, cfg, version)
}

func runSetup(ctx context.Context, args []string) error {
	flags := flag.NewFlagSet("setup", flag.ContinueOnError)
	projectRoot := flags.String("project-root", "", "Elysium project root")
	elysiumHome := flags.String("elysium-home", "", "Elysium data home")
	binary := flags.String("binary", "", "MCP server binary path")
	client := flags.String("client", "both", "codex, claude, or both")
	scope := flags.String("scope", "project", "Claude scope: project or user")
	serverName := flags.String("server-name", "elysium", "MCP server name")
	flags.SetOutput(os.Stderr)
	if err := flags.Parse(args); err != nil {
		return err
	}
	cfg, err := config.Resolve(*projectRoot, *elysiumHome, *binary)
	if err != nil {
		return err
	}
	result, err := setup.Run(ctx, cfg, setup.Options{
		Client:     *client,
		Scope:      *scope,
		ServerName: *serverName,
	})
	if err != nil {
		return err
	}
	return printJSON(result)
}

func runStatus(ctx context.Context, args []string) error {
	flags := flag.NewFlagSet("status", flag.ContinueOnError)
	projectRoot := flags.String("project-root", "", "Elysium project root")
	elysiumHome := flags.String("elysium-home", "", "Elysium data home")
	flags.SetOutput(os.Stderr)
	if err := flags.Parse(args); err != nil {
		return err
	}
	cfg, err := config.Resolve(*projectRoot, *elysiumHome, "")
	if err != nil {
		return err
	}
	db, err := store.Open(ctx, cfg)
	if err != nil {
		return err
	}
	defer db.Close()
	status, err := db.Status(ctx)
	if err != nil {
		return err
	}
	return printJSON(status)
}

func printJSON(value any) error {
	encoded, err := json.MarshalIndent(value, "", "  ")
	if err != nil {
		return err
	}
	fmt.Println(string(encoded))
	return nil
}

func usage() string {
	return `elysium-mcp

Commands:
  server   Run the MCP server over stdio
  setup    Register the MCP server with Codex and Claude Code
  status   Print read-only Elysium memory status
  version  Print the binary version

`
}
