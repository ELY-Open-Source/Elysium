package hook

import (
	"encoding/json"
	"io"
	"sort"
	"strings"
)

// dialect is one client's hook payload in and answer out, plus how it behaves around a turn.
type dialect struct {
	read  func(raw map[string]any) Input
	write func(stdout io.Writer, event Event, context string) error
	// approve answers a permission request for one of Elysian's own tools; nil when the client needs none.
	approve func(stdout io.Writer, raw map[string]any) error
	// failExit reports a failure without blocking the turn: some clients block on 2, Kiro hands any
	// non-zero code to the agent.
	failExit int
	// repeats marks a prompt hook that fires before every model call, not once per prompt.
	repeats bool
	// captureOnly marks a client that discards what a prompt hook prints, so recall is skipped.
	captureOnly bool
	// noSessionHook marks a client whose session-start output is lost; its first prompt carries it.
	noSessionHook bool
	// foreign reports a payload from another agent that runs this client's hooks too.
	foreign func(raw map[string]any) bool
}

var dialects = map[string]dialect{
	"claude":   {read: readCommon, write: hookSpecific(claudeEvents), approve: allowHookSpecific, failExit: 1, foreign: borrowed},
	"codex":    {read: readCommon, write: hookSpecific(claudeEvents), failExit: 1},
	"droid":    {read: readCommon, write: hookSpecific(claudeEvents), approve: allowHookSpecific, failExit: 1},
	"qwen":     {read: readQwen, write: hookSpecific(claudeEvents), failExit: 1},
	"gemini":   {read: readCommon, write: hookSpecific(geminiEvents), failExit: 1},
	"kiro":     {read: readCommon, write: writePlain, failExit: 0},
	"agy":      {read: readAntigravity, write: writeInjectSteps, failExit: 1, repeats: true},
	"kimi":     {read: readCommon, write: writePlain, failExit: 0, noSessionHook: true},
	"copilot":  {read: readCommon, write: writeTopLevel, approve: allowCopilot, failExit: 1},
	"cursor":   {read: readCommon, write: writeCursor, failExit: 1},
	"grok":     {read: readCommon, write: writeNothing, failExit: 0, captureOnly: true},
	"kigi":     {read: readCommon, write: writeNothing, failExit: 0, captureOnly: true},
	"opencode": {read: readCommon, write: writePlain, failExit: 1},
}

// FailExit is the exit code a failed hook returns for this client.
func FailExit(client string) int {
	if d, ok := dialects[client]; ok {
		return d.failExit
	}
	return 1
}

func clientNames() []string {
	names := make([]string, 0, len(dialects))
	for name := range dialects {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}

// field returns the first key present as text; a list of content parts is joined, as Kimi sends a prompt.
func field(raw map[string]any, keys ...string) string {
	for _, key := range keys {
		switch value := raw[key].(type) {
		case string:
			if value != "" {
				return value
			}
		case []any:
			var parts []string
			for _, item := range value {
				switch part := item.(type) {
				case string:
					parts = append(parts, part)
				case map[string]any:
					if text, ok := part["text"].(string); ok {
						parts = append(parts, text)
					}
				}
			}
			if joined := strings.TrimSpace(strings.Join(parts, "\n")); joined != "" {
				return joined
			}
		}
	}
	return ""
}

// readCommon reads the Claude Code payload and the names other clients gave the same fields.
func readCommon(raw map[string]any) Input {
	in := Input{
		Prompt:    field(raw, "prompt"),
		SessionID: field(raw, "session_id", "sessionId", "conversation_id", "conversationId"),
		Cwd:       field(raw, "cwd", "workspaceRoot", "workspace_root"),
	}
	if in.Cwd == "" {
		in.Cwd = first(raw, "workspace_roots")
	}
	return in
}

func first(raw map[string]any, key string) string {
	if list, ok := raw[key].([]any); ok && len(list) > 0 {
		text, _ := list[0].(string)
		return text
	}
	return ""
}

// readQwen prefers the raw text the user typed over the expanded prompt.
func readQwen(raw map[string]any) Input {
	in := readCommon(raw)
	if submitted := field(raw, "submitted_prompt"); submitted != "" {
		in.Prompt = submitted
	}
	return in
}

// readAntigravity reads agy's camelCase payload; its first workspace stands for the cwd.
func readAntigravity(raw map[string]any) Input {
	return Input{Prompt: field(raw, "lastUserInput"), SessionID: field(raw, "conversationId"), Cwd: first(raw, "workspacePaths")}
}

// borrowed spots Cursor, Grok and Kigi running Claude Code's hooks: each has its own Elysian hook.
func borrowed(raw map[string]any) bool {
	_, cursor := raw["cursor_version"]
	_, camel := raw["hookEventName"]
	return cursor || camel
}

// The client's names for our events: Claude Code's, which Codex, Droid and Qwen copied, and Gemini's.
var (
	claudeEvents = map[Event]string{SessionStart: "SessionStart", Prompt: "UserPromptSubmit"}
	geminiEvents = map[Event]string{SessionStart: "SessionStart", Prompt: "BeforeAgent"}
)

// hookSpecific answers with hookSpecificOutput.additionalContext.
func hookSpecific(names map[Event]string) func(io.Writer, Event, string) error {
	return func(stdout io.Writer, event Event, context string) error {
		if context == "" {
			return nil
		}
		return encode(stdout, map[string]any{"hookSpecificOutput": map[string]any{"hookEventName": names[event], "additionalContext": context}})
	}
}

// allowHookSpecific approves a PreToolUse the client already matched to mcp__elysian__.
func allowHookSpecific(stdout io.Writer, _ map[string]any) error {
	return encode(stdout, map[string]any{"hookSpecificOutput": map[string]any{
		"hookEventName": "PreToolUse", "permissionDecision": "allow", "permissionDecisionReason": "Elysian's own memory tools",
	}})
}

// allowCopilot approves only Elysian's tools; for any other tool it says nothing and Copilot asks as usual.
func allowCopilot(stdout io.Writer, raw map[string]any) error {
	if !strings.Contains(strings.ToLower(field(raw, "toolName", "tool_name")), "elysian") {
		return nil
	}
	return encode(stdout, map[string]any{"behavior": "allow"})
}

// writeTopLevel is Copilot's shape: additionalContext at the top of the answer.
func writeTopLevel(stdout io.Writer, _ Event, context string) error {
	if context == "" {
		return nil
	}
	return encode(stdout, map[string]any{"additionalContext": context})
}

// writeCursor answers sessionStart with additional_context and lets every prompt continue.
func writeCursor(stdout io.Writer, event Event, context string) error {
	answer := map[string]any{}
	if event == Prompt {
		answer["continue"] = true
	}
	if context != "" {
		answer["additional_context"] = context
	}
	if len(answer) == 0 {
		return nil
	}
	return encode(stdout, answer)
}

// writePlain prints the context itself; the client adds stdout to the model's context.
func writePlain(stdout io.Writer, _ Event, context string) error {
	if context == "" {
		return nil
	}
	_, err := io.WriteString(stdout, context+"\n")
	return err
}

// writeInjectSteps answers agy with one transient system message.
func writeInjectSteps(stdout io.Writer, _ Event, context string) error {
	if context == "" {
		return nil
	}
	return encode(stdout, map[string]any{"injectSteps": []any{map[string]any{"ephemeralMessage": context}}})
}

// writeNothing is for a client that throws prompt-hook output away.
func writeNothing(io.Writer, Event, string) error { return nil }

func encode(stdout io.Writer, value any) error {
	return json.NewEncoder(stdout).Encode(value)
}
