package setup

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"
)

// editJSON applies change to the JSON object in path, creating it when absent; a file that is not
// a JSON object is left untouched and named, so a hand-written config is never clobbered.
func editJSON(path string, change func(document map[string]any) error) error {
	document := map[string]any{}
	data, err := os.ReadFile(path)
	if err == nil && strings.TrimSpace(string(data)) != "" {
		if err := json.Unmarshal(data, &document); err != nil {
			return errors.New(path + " is not a JSON object, so it was left untouched: " + err.Error())
		}
	} else if err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if err := change(document); err != nil {
		return err
	}
	var encoded bytes.Buffer
	encoder := json.NewEncoder(&encoded)
	encoder.SetEscapeHTML(false)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(document); err != nil {
		return err
	}
	return writeAtomic(path, encoded.Bytes())
}

// editJSONRead hands a readable JSON object in path to look; an absent or broken file shows nothing.
func editJSONRead(path string, look func(document map[string]any)) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	document := map[string]any{}
	if err := json.Unmarshal(data, &document); err != nil {
		return err
	}
	look(document)
	return nil
}

func writeAtomic(path string, data []byte) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	temporary := path + ".elysian-tmp"
	if err := os.WriteFile(temporary, data, 0o600); err != nil {
		return err
	}
	return os.Rename(temporary, path)
}

// object returns document[key] as an object, making it when absent and refusing any other type.
func object(document map[string]any, key, path string) (map[string]any, error) {
	switch value := document[key].(type) {
	case nil:
		made := map[string]any{}
		document[key] = made
		return made, nil
	case map[string]any:
		return value, nil
	default:
		return nil, errors.New(path + ` holds a "` + key + `" that is not an object, so it was left untouched`)
	}
}

// addString appends value to the list document[key] unless it is there already.
func addString(document map[string]any, key, value, path string) error {
	list, ok := document[key].([]any)
	if document[key] != nil && !ok {
		return errors.New(path + ` holds a "` + key + `" that is not a list, so it was left untouched`)
	}
	for _, item := range list {
		if item == value {
			return nil
		}
	}
	document[key] = append(list, value)
	return nil
}

// ours spots a handler an earlier setup wrote: it runs elysian-mcp's hook command.
func ours(handler any) bool {
	text, _ := json.Marshal(handler)
	return strings.Contains(string(text), "elysian-mcp") && strings.Contains(string(text), "hook")
}

// replaceGroups swaps our groups under one Claude-style event (event -> [{matcher, hooks:[...]}])
// for fresh ones and keeps every other group, so a re-run never stacks duplicates.
func replaceGroups(hooks map[string]any, event string, fresh []any, path string) error {
	groups, ok := hooks[event].([]any)
	if hooks[event] != nil && !ok {
		return errors.New(path + ` holds hooks.` + event + ` that is not a list, so it was left untouched`)
	}
	kept := []any{}
	for _, group := range groups {
		if entry, ok := group.(map[string]any); ok {
			if handlers, ok := entry["hooks"].([]any); ok && len(handlers) > 0 && allOurs(handlers) {
				continue
			}
		}
		if ours(group) {
			continue
		}
		kept = append(kept, group)
	}
	hooks[event] = append(kept, fresh...)
	return nil
}

func allOurs(handlers []any) bool {
	for _, handler := range handlers {
		if !ours(handler) {
			return false
		}
	}
	return true
}

// plainPath matches a path every shell runs unquoted.
var plainPath = regexp.MustCompile(`^[A-Za-z0-9_./:\\-]+$`)

// shellCommand is the hook command line for a client's shell: posix sh, cmd.exe or PowerShell.
func shellCommand(binary, shell string, args ...string) string {
	program := binary
	if !plainPath.MatchString(binary) {
		switch shell {
		case "pwsh":
			program = `& '` + strings.ReplaceAll(binary, `'`, `''`) + `'`
		case "cmd":
			program = `"` + binary + `"`
		default:
			program = `'` + strings.ReplaceAll(binary, `'`, `'\''`) + `'`
		}
	} else if shell == "pwsh" {
		program = "& " + binary
	}
	return program + " " + strings.Join(args, " ")
}

// windowsShell picks the shell a client's hooks run in on this OS.
func windowsShell(onWindows string) string {
	if runtime.GOOS == "windows" {
		return onWindows
	}
	return "sh"
}

// managedBlock replaces the text between our markers in a file, or appends it, keeping the rest;
// comment is "#" for TOML or "<!--" for Markdown.
func managedBlock(path, comment, body string) error {
	tail := ""
	if comment == "<!--" {
		tail = " -->"
	}
	begin, end := comment+" >>> elysian (written by elysian-mcp setup)"+tail, comment+" <<< elysian"+tail
	data, err := os.ReadFile(path)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	text := string(data)
	if i := strings.Index(text, begin); i >= 0 {
		j := strings.Index(text[i:], end)
		if j < 0 {
			return errors.New(path + " has an opening elysian marker with no closing one; fix it by hand")
		}
		text = text[:i] + text[i+j+len(end):]
	}
	text = strings.TrimRight(text, "\n")
	if text != "" {
		text += "\n\n"
	}
	return writeAtomic(path, []byte(text+begin+"\n"+strings.TrimRight(body, "\n")+"\n"+end+"\n"))
}

// configHome returns the env override when set, else ~/name.
func configHome(env, name string) (string, error) {
	if dir := os.Getenv(env); dir != "" {
		return dir, nil
	}
	user, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(user, name), nil
}

// hookArgs is the argument list every hook runs with; a home setup was given rides along.
func hookArgs(server entry, client, event string) []string {
	args := []string{"hook", "--client", client}
	if home := server.Env["ELYSIAN_HOME"]; home != "" {
		args = append(args, "--elysian-home", home)
	}
	return append(args, event)
}
