package cli

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/backend"
	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/config"
	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/mcpserver"
	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/setup"
	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/store"
)

// version is stamped at release build time via -ldflags -X. The default is the
// development version used by source builds.
var version = "0.2.1"

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
	projectRoot := flags.String("project-root", "", "Elysian project root")
	elysianHome := flags.String("elysian-home", "", "Elysian data home")
	flags.SetOutput(os.Stderr)
	if err := flags.Parse(args); err != nil {
		return err
	}
	cfg, err := config.Resolve(*projectRoot, *elysianHome, "")
	if err != nil {
		return err
	}
	if err := backend.Ensure(ctx, cfg.APIBaseURL, cfg.ElysianHome); err != nil {
		return err
	}
	if err := config.RequireDatabase(cfg); err != nil {
		return err
	}
	return mcpserver.Run(ctx, cfg, version)
}

func runSetup(ctx context.Context, args []string) error {
	flags := flag.NewFlagSet("setup", flag.ContinueOnError)
	elysianHome := flags.String("elysian-home", "", "Elysian data home")
	binary := flags.String("binary", "", "MCP server binary path")
	client := flags.String("client", "all", "all installed clients, or one of codex, claude, cursor, gemini, opencode, vscode")
	serverName := flags.String("server-name", "elysian", "MCP server name")
	flags.SetOutput(os.Stderr)
	if err := flags.Parse(args); err != nil {
		return err
	}
	cfg, err := config.Resolve("", *elysianHome, *binary)
	if err != nil {
		return err
	}
	options := setup.Options{Client: *client, ServerName: *serverName}
	if *elysianHome != "" || os.Getenv("ELYSIAN_HOME") != "" {
		options.Home = cfg.ElysianHome
	}
	result, err := setup.Run(ctx, cfg, options)
	if err != nil {
		return err
	}
	return printJSON(result)
}

func runStatus(ctx context.Context, args []string) error {
	flags := flag.NewFlagSet("status", flag.ContinueOnError)
	projectRoot := flags.String("project-root", "", "Elysian project root")
	elysianHome := flags.String("elysian-home", "", "Elysian data home")
	flags.SetOutput(os.Stderr)
	if err := flags.Parse(args); err != nil {
		return err
	}
	cfg, err := config.Resolve(*projectRoot, *elysianHome, "")
	if err != nil {
		return err
	}
	if err := config.RequireDatabase(cfg); err != nil {
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
	return `elysian-mcp

Commands:
  server   Run the MCP server over stdio
  setup    Register the MCP server user-wide with every installed coding agent
  status   Print read-only Elysian memory status
  version  Print the binary version

`
}
