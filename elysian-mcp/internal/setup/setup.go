// Package setup registers the MCP server, user-wide, with the coding agents installed here.
package setup

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"os/exec"
	"strings"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/config"
)

type Options struct {
	Client     string
	ServerName string
}

type Action struct {
	Client  string `json:"client"`
	Target  string `json:"target"`
	Detail  string `json:"detail"`
	Command string `json:"command,omitempty"`
}

type Result struct {
	ServerName string   `json:"server_name"`
	Binary     string   `json:"binary"`
	Actions    []Action `json:"actions"`
}

type client struct {
	name     string
	program  string
	register func(context.Context, string, config.Config, string) (Action, error)
}

var clients = []client{
	{"codex", "codex", registerCodex},
	{"claude", "claude", registerClaude},
}

// Run registers with every installed client, or only the one named; a named client that is missing is an error.
func Run(ctx context.Context, cfg config.Config, options Options) (Result, error) {
	if cfg.Binary == "" {
		return Result{}, errors.New("binary path is required for setup")
	}
	serverName := options.ServerName
	if serverName == "" {
		serverName = "elysian"
	}
	wanted := strings.ToLower(strings.TrimSpace(options.Client))
	if wanted == "" {
		wanted = "all"
	}
	result := Result{ServerName: serverName, Binary: cfg.Binary}
	for _, each := range clients {
		if wanted != "all" && wanted != each.name {
			continue
		}
		program, err := exec.LookPath(each.program)
		if err != nil {
			if wanted == each.name {
				return Result{}, errors.New(each.program + " is not on PATH, so " + each.name + " cannot be registered")
			}
			result.Actions = append(result.Actions, Action{Client: each.name, Detail: "not installed; skipped"})
			continue
		}
		action, err := each.register(ctx, program, cfg, serverName)
		if err != nil {
			return Result{}, err
		}
		result.Actions = append(result.Actions, action)
	}
	if len(result.Actions) == 0 {
		return Result{}, errors.New("client must be all, codex or claude, got " + options.Client)
	}
	return result, nil
}

// serverEnv carries ELYSIAN_HOME only when the user named one; otherwise the server finds ~/.elysian itself.
func serverEnv() map[string]string {
	env := map[string]string{}
	if home := os.Getenv("ELYSIAN_HOME"); home != "" {
		env["ELYSIAN_HOME"] = home
	}
	return env
}

func registerCodex(ctx context.Context, codex string, cfg config.Config, serverName string) (Action, error) {
	args := []string{"mcp", "add", serverName}
	for key, value := range serverEnv() {
		args = append(args, "--env", key+"="+value)
	}
	args = append(args, "--", cfg.Binary, "server")
	if output, err := exec.CommandContext(ctx, codex, args...).CombinedOutput(); err != nil {
		return Action{}, errors.New("codex mcp add failed: " + strings.TrimSpace(string(output)))
	}
	return Action{Client: "codex", Target: "~/.codex/config.toml", Detail: "registered user-wide", Command: commandLine(codex, args)}, nil
}

func registerClaude(ctx context.Context, claude string, cfg config.Config, serverName string) (Action, error) {
	payload, err := json.Marshal(map[string]any{"type": "stdio", "command": cfg.Binary, "args": []string{"server"}, "env": serverEnv()})
	if err != nil {
		return Action{}, err
	}
	// add-json refuses a name that exists, so a re-run removes it first; absence is the only failure allowed.
	removed, err := exec.CommandContext(ctx, claude, "mcp", "remove", serverName, "--scope", "user").CombinedOutput()
	if err != nil && !strings.Contains(string(removed), `No MCP server named "`+serverName+`" in user scope`) {
		return Action{}, errors.New("claude mcp remove failed: " + strings.TrimSpace(string(removed)))
	}
	args := []string{"mcp", "add-json", serverName, string(payload), "--scope", "user"}
	if output, err := exec.CommandContext(ctx, claude, args...).CombinedOutput(); err != nil {
		return Action{}, errors.New("claude mcp add-json failed: " + strings.TrimSpace(string(output)))
	}
	return Action{Client: "claude", Target: "~/.claude.json", Detail: "registered user-wide", Command: commandLine(claude, args)}, nil
}

func commandLine(program string, args []string) string {
	quoted := []string{program}
	for _, part := range args {
		if strings.ContainsAny(part, " \t\"'") {
			part = `"` + strings.ReplaceAll(part, `"`, `\"`) + `"`
		}
		quoted = append(quoted, part)
	}
	return strings.Join(quoted, " ")
}
