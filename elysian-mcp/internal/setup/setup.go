// Package setup registers the MCP server, user-wide, with the coding agents installed here.
package setup

import (
	"context"
	"encoding/json"
	"errors"
	"os/exec"
	"strings"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/config"
)

type Options struct {
	Client     string
	ServerName string
	// Home is the resolved home when the user named one; empty lets the server find ~/.elysian.
	Home string
}

// entry is what every client is told to run.
type entry struct {
	Name   string
	Binary string
	Env    map[string]string
}

type Action struct {
	Client  string `json:"client"`
	Target  string `json:"target"`
	Detail  string `json:"detail"`
	Command string `json:"command,omitempty"`
}

type Result struct {
	ServerName     string         `json:"server_name"`
	Binary         string         `json:"binary"`
	Actions        []Action       `json:"actions"`
	AnyOtherClient map[string]any `json:"any_other_client"`
}

type client struct {
	name string
	// find returns the client's CLI, or for Cursor its config file.
	find     func() (string, error)
	register func(context.Context, string, entry) (Action, error)
}

func onPath(program string) func() (string, error) {
	return func() (string, error) { return exec.LookPath(program) }
}

var clients = []client{
	{"codex", onPath("codex"), registerCodex},
	{"claude", onPath("claude"), registerClaude},
	{"droid", onPath("droid"), registerDroid},
	{"qwen", onPath("qwen"), registerQwen},
	{"kiro", onPath("kiro-cli"), registerKiro},
	{"agy", onPath("agy"), registerAntigravity},
	{"kimi", onPath("kimi"), registerKimi},
	{"copilot", onPath("copilot"), registerCopilot},
	{"grok", onPath("grok"), registerGrok},
	{"kigi", onPath("kigi"), registerKigi},
	{"cursor", cursorFile, registerCursor},
	{"gemini", onPath("gemini"), registerGemini},
	{"opencode", onPath("opencode"), registerOpenCode},
	{"vscode", onPath("code"), registerVSCode},
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
	server := entry{Name: serverName, Binary: cfg.Binary, Env: map[string]string{}}
	if options.Home != "" {
		server.Env["ELYSIAN_HOME"] = options.Home
	}
	result := Result{ServerName: serverName, Binary: cfg.Binary}
	for _, each := range clients {
		if wanted != "all" && wanted != each.name {
			continue
		}
		program, err := each.find()
		if err != nil {
			if wanted == each.name {
				return Result{}, errors.New(each.name + " is not installed here (" + err.Error() + "), so it cannot be registered")
			}
			result.Actions = append(result.Actions, Action{Client: each.name, Detail: "not installed; skipped"})
			continue
		}
		action, err := each.register(ctx, program, server)
		if err != nil {
			return Result{}, err
		}
		result.Actions = append(result.Actions, action)
	}
	if len(result.Actions) == 0 {
		names := []string{"all"}
		for _, each := range clients {
			names = append(names, each.name)
		}
		return Result{}, errors.New("client must be one of " + strings.Join(names, ", ") + ", got " + options.Client)
	}
	result.AnyOtherClient = generic(server)
	return result, nil
}

// registerCodex writes the server, its approval mode and its trusted hooks in one edit of Codex's
// files; `codex mcp add` cannot set the approval mode.
func registerCodex(ctx context.Context, codex string, server entry) (Action, error) {
	target, err := wireCodex(ctx, codex, server)
	if err != nil {
		return Action{}, err
	}
	return Action{Client: "codex", Target: target, Detail: "registered user-wide, Elysian's tools approved; session and prompt hooks, trusted"}, nil
}

func registerClaude(ctx context.Context, claude string, server entry) (Action, error) {
	payload, err := json.Marshal(map[string]any{"type": "stdio", "command": server.Binary, "args": []string{"server"}, "env": server.Env})
	if err != nil {
		return Action{}, err
	}
	// add-json refuses a name that exists, so a re-run removes it first; absence is the only failure allowed.
	removed, err := exec.CommandContext(ctx, claude, "mcp", "remove", server.Name, "--scope", "user").CombinedOutput()
	if err != nil && !strings.Contains(string(removed), `No MCP server named "`+server.Name+`" in user scope`) {
		return Action{}, errors.New("claude mcp remove failed: " + strings.TrimSpace(string(removed)))
	}
	args := []string{"mcp", "add-json", server.Name, string(payload), "--scope", "user"}
	if output, err := exec.CommandContext(ctx, claude, args...).CombinedOutput(); err != nil {
		return Action{}, errors.New("claude mcp add-json failed: " + strings.TrimSpace(string(output)))
	}
	settings, err := wireClaude(ctx, claude, server)
	if err != nil {
		return Action{}, err
	}
	return Action{Client: "claude", Target: "~/.claude.json and " + settings, Detail: "registered user-wide; session and prompt hooks; Elysian's tools approved", Command: commandLine(claude, args)}, nil
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
