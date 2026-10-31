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

	"github.com/pelletier/go-toml/v2"
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

// replaceGroups drops our handlers under one Claude-style event (event -> [{matcher, hooks:[...]}]),
// keeping every other handler and any group still holding one, then appends fresh groups; a re-run
// never stacks duplicates and never takes a user's handler with ours.
func replaceGroups(hooks map[string]any, event string, fresh []any, path string) error {
	groups, ok := hooks[event].([]any)
	if hooks[event] != nil && !ok {
		return errors.New(path + ` holds hooks.` + event + ` that is not a list, so it was left untouched`)
	}
	kept := []any{}
	for _, group := range groups {
		entry, isGroup := group.(map[string]any)
		handlers, hasHandlers := entry["hooks"].([]any)
		if !isGroup || !hasHandlers {
			kept = append(kept, group)
			continue
		}
		theirs := []any{}
		for _, handler := range handlers {
			if !ours(handler) {
				theirs = append(theirs, handler)
			}
		}
		if len(theirs) == 0 {
			continue
		}
		entry["hooks"] = theirs
		kept = append(kept, entry)
	}
	hooks[event] = append(kept, fresh...)
	return nil
}

// plainPath matches a path every shell runs unquoted.
var plainPath = regexp.MustCompile(`^[A-Za-z0-9_./:\\-]+$`)

// shellCommand is the hook command line for a client's shell: posix sh, cmd.exe or PowerShell;
// every word that needs it is quoted, the program and its arguments alike.
func shellCommand(binary, shell string, args ...string) string {
	words := make([]string, 0, len(args)+1)
	for _, word := range append([]string{binary}, args...) {
		words = append(words, quote(word, shell))
	}
	if shell == "pwsh" {
		return "& " + strings.Join(words, " ")
	}
	return strings.Join(words, " ")
}

func quote(word, shell string) string {
	if plainPath.MatchString(word) {
		return word
	}
	switch shell {
	case "pwsh":
		return `'` + strings.ReplaceAll(word, `'`, `''`) + `'`
	case "cmd":
		return `"` + word + `"`
	default:
		return `'` + strings.ReplaceAll(word, `'`, `'\''`) + `'`
	}
}

// windowsShell picks the shell a client's hooks run in on this OS.
func windowsShell(onWindows string) string {
	if runtime.GOOS == "windows" {
		return onWindows
	}
	return "sh"
}

// withBlock returns text with the part between our markers replaced, or the block appended;
// comment is "#" for TOML or "<!--" for Markdown.
func withBlock(text, comment, body string) (string, error) {
	tail := ""
	if comment == "<!--" {
		tail = " -->"
	}
	begin, end := comment+" >>> elysian (written by elysian-mcp setup)"+tail, comment+" <<< elysian"+tail
	if i := strings.Index(text, begin); i >= 0 {
		j := strings.Index(text[i:], end)
		if j < 0 {
			return "", errors.New("an opening elysian marker has no closing one; fix it by hand")
		}
		text = text[:i] + text[i+j+len(end):]
	}
	text = strings.TrimRight(text, "\n")
	if text != "" {
		text += "\n\n"
	}
	return text + begin + "\n" + strings.TrimRight(body, "\n") + "\n" + end + "\n", nil
}

// managedBlock writes our marked block into a Markdown file, keeping the rest.
func managedBlock(path, comment, body string) error {
	data, err := os.ReadFile(path)
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	text, err := withBlock(string(data), comment, body)
	if err != nil {
		return errors.New(path + ": " + err.Error())
	}
	return writeAtomic(path, []byte(text))
}

// readTOML parses a TOML file, absent meaning empty; a file that does not parse stops setup.
func readTOML(path string) (string, map[string]any, error) {
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return "", map[string]any{}, nil
	}
	if err != nil {
		return "", nil, err
	}
	document := map[string]any{}
	if err := toml.Unmarshal(data, &document); err != nil {
		return "", nil, errors.New(path + " is not valid TOML, so it was left untouched: " + err.Error())
	}
	return string(data), document, nil
}

// writeTOMLBlock writes our block into text and refuses to save a result that does not parse.
func writeTOMLBlock(path, text, body string) error {
	updated, err := withBlock(text, "#", body)
	if err != nil {
		return errors.New(path + ": " + err.Error())
	}
	if err := toml.Unmarshal([]byte(updated), &map[string]any{}); err != nil {
		return errors.New("Elysian's entries would make " + path + " invalid TOML, so it was left untouched: " + err.Error())
	}
	return writeAtomic(path, []byte(updated))
}

// tomlHas reports whether a dotted path exists in a parsed TOML document.
func tomlHas(document map[string]any, keys ...string) bool {
	var node any = document
	for _, key := range keys {
		table, ok := node.(map[string]any)
		if !ok {
			return false
		}
		if node, ok = table[key]; !ok {
			return false
		}
	}
	return true
}

// userDir is ~/name, for a client that documents no override.
func userDir(name string) (string, error) {
	return configHome("", name)
}

// configHome returns the env override when set, else ~/name.
func configHome(env, name string) (string, error) {
	if dir := os.Getenv(env); env != "" && dir != "" {
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
