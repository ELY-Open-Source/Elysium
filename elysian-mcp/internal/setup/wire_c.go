package setup

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

// recallInstruction tells a model to recall when its client cannot inject memories on a prompt.
const recallInstruction = "Elysian local memory is connected as the MCP server `elysian`. What the user says is saved to it automatically, but this agent cannot add recalled memories to a prompt by itself: at the start of each task, call the elysian tool `search_atoms` with the user's request (through use_tool when tools are discovered on demand) and use what it returns. Call `remember` for a durable fact the user did not state."

// grokFamily is xAI's Grok Build and its fork Kigi: one config.toml, a hooks directory, and no way
// for a prompt hook to reach the model, so hooks save and an instruction recalls.
type grokFamily struct {
	client, homeEnv, homeName string
	// instructions is the file the model always reads, relative to the client's home.
	instructions string
	// ownFile marks instructions that are Elysian's alone; otherwise a marked block is kept in it.
	ownFile bool
}

var (
	grok = grokFamily{client: "grok", homeEnv: "GROK_HOME", homeName: ".grok", instructions: filepath.Join("rules", "elysian.md"), ownFile: true}
	kigi = grokFamily{client: "kigi", homeEnv: "KIGI_HOME", homeName: ".kigi", instructions: "AGENTS.md"}
)

func registerGrok(ctx context.Context, program string, server entry) (Action, error) {
	return grok.register(ctx, program, server)
}

func registerKigi(ctx context.Context, program string, server entry) (Action, error) {
	return kigi.register(ctx, program, server)
}

func (f grokFamily) register(_ context.Context, _ string, server entry) (Action, error) {
	dir, err := configHome(f.homeEnv, f.homeName)
	if err != nil {
		return Action{}, err
	}
	if _, err := os.Stat(filepath.Join(dir, "user-settings.json")); err == nil && f.client == "grok" {
		return Action{Client: f.client, Detail: "skipped: this `grok` is the community grok-cli (~/.grok/user-settings.json), whose hooks discard their output; xAI's Grok Build is supported"}, nil
	}
	configPath := filepath.Join(dir, "config.toml")
	existing, err := os.ReadFile(configPath)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return Action{}, err
	}
	theirs := outsideBlock(string(existing))
	var block, notes []string
	if strings.Contains(theirs, "[mcp_servers."+server.Name+"]") {
		notes = append(notes, "kept the [mcp_servers."+server.Name+"] already in "+configPath)
	} else {
		table := "[mcp_servers." + server.Name + "]\ncommand = \"" + tomlEscape(server.Binary) + "\"\nargs = [\"server\"]\nenabled = true"
		if home := server.Env["ELYSIAN_HOME"]; home != "" {
			table += "\n\n[mcp_servers." + server.Name + ".env]\nELYSIAN_HOME = \"" + tomlEscape(home) + "\""
		}
		block = append(block, table)
	}
	if regexp.MustCompile(`(?m)^\s*(\[permission\]|permission\s*[.=])`).MatchString(theirs) {
		notes = append(notes, "add \"MCPTool("+server.Name+"__*)\" to [permission].allow in "+configPath+" by hand")
	} else {
		block = append(block, "[permission]\nallow = [\"MCPTool("+server.Name+"__*)\"]")
	}
	if err := managedBlock(configPath, "#", strings.Join(block, "\n\n")); err != nil {
		return Action{}, err
	}
	command, err := plainCommand(server.Binary, windowsShell("plain"), hookArgs(server, f.client, "prompt")...)
	if err != nil {
		return Action{}, err
	}
	hookPath := filepath.Join(dir, "hooks", "elysian.json")
	if err := editJSON(hookPath, func(document map[string]any) error {
		document["hooks"] = map[string]any{"UserPromptSubmit": []any{map[string]any{"hooks": []any{map[string]any{"type": "command", "command": command, "timeout": 10}}}}}
		return nil
	}); err != nil {
		return Action{}, err
	}
	instructions := filepath.Join(dir, f.instructions)
	if f.ownFile {
		err = writeAtomic(instructions, []byte(recallInstruction+"\n"))
	} else {
		err = managedBlock(instructions, "<!--", recallInstruction)
	}
	if err != nil {
		return Action{}, err
	}
	detail := "registered user-wide; prompts saved by a hook; recall by instruction (" + f.client + " hooks cannot add context)"
	if len(notes) > 0 {
		detail += "; " + strings.Join(notes, "; ")
	}
	return Action{Client: f.client, Target: configPath + ", " + hookPath + ", " + instructions, Detail: detail}, nil
}
