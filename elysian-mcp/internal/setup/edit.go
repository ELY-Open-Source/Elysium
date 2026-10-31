package setup

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"runtime"
	"slices"
	"strings"

	"github.com/pelletier/go-toml/v2"
)

// editJSON applies change to the JSON object in path, creating it when absent; a file that is not
// a JSON object is left untouched and named, so a hand-written config is never clobbered.
func editJSON(path string, change func(document map[string]any) error) error {
	encoded, err := planJSON(path, change)
	if err != nil {
		return err
	}
	return writeAtomic(path, encoded)
}

// planJSON is editJSON without the write, for a change that must land with another file or not at all.
func planJSON(path string, change func(document map[string]any) error) ([]byte, error) {
	document := map[string]any{}
	data, err := os.ReadFile(path)
	if err == nil && strings.TrimSpace(string(data)) != "" {
		if err := json.Unmarshal(data, &document); err != nil {
			return nil, errors.New(path + " is not a JSON object, so it was left untouched: " + err.Error())
		}
	} else if err != nil && !errors.Is(err, os.ErrNotExist) {
		return nil, err
	}
	if err := change(document); err != nil {
		return nil, err
	}
	var encoded bytes.Buffer
	encoder := json.NewEncoder(&encoded)
	encoder.SetEscapeHTML(false)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(document); err != nil {
		return nil, err
	}
	return encoded.Bytes(), nil
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

// replaceGroups puts fresh groups under one Claude-style event (event -> [{matcher, hooks:[...]}]) where
// ours stood, so no other group changes position (Codex ties a hook's trust to its position); our
// handlers leave mixed groups, a user's handler never leaves with them, and a re-run adds nothing.
func replaceGroups(hooks map[string]any, event string, fresh []any, path string) error {
	groups, ok := hooks[event].([]any)
	if hooks[event] != nil && !ok {
		return errors.New(path + ` holds hooks.` + event + ` that is not a list, so it was left untouched`)
	}
	kept, placed := []any{}, false
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
		switch {
		case len(theirs) == len(handlers):
			kept = append(kept, group)
		case len(theirs) > 0:
			entry["hooks"] = theirs
			kept = append(kept, entry)
		case !placed:
			kept, placed = append(kept, fresh...), true
		}
	}
	if !placed {
		kept = append(kept, fresh...)
	}
	hooks[event] = kept
	return nil
}

// Words a shell reads literally without quotes: POSIX shells treat a backslash as an escape,
// Windows shells read it as a path separator.
var (
	plainPosix   = regexp.MustCompile(`^[A-Za-z0-9_./:-]+$`)
	plainWindows = regexp.MustCompile(`^[A-Za-z0-9_./:\\-]+$`)
)

// shellCommand is the hook command line for a client's shell: "sh", "cmd", "pwsh", or "plain" for a
// Windows shell nobody documented, which takes only words that need no quoting at all.
func shellCommand(binary, shell string, args ...string) (string, error) {
	words := make([]string, 0, len(args)+1)
	for _, word := range append([]string{binary}, args...) {
		quoted, err := quote(word, shell)
		if err != nil {
			return "", err
		}
		words = append(words, quoted)
	}
	if shell == "pwsh" {
		return "& " + strings.Join(words, " "), nil
	}
	return strings.Join(words, " "), nil
}

func quote(word, shell string) (string, error) {
	switch shell {
	case "sh":
		if plainPosix.MatchString(word) {
			return word, nil
		}
		return `'` + strings.ReplaceAll(word, `'`, `'\''`) + `'`, nil
	case "pwsh":
		if plainWindows.MatchString(word) {
			return word, nil
		}
		return `'` + strings.ReplaceAll(word, `'`, `''`) + `'`, nil
	case "cmd":
		// cmd.exe expands %VARIABLES% even inside quotes, and a quote cannot be escaped in one.
		if strings.ContainsAny(word, `%"`) {
			return "", errors.New(word + " holds % or \", which cmd.exe cannot pass through literally; use a path without them")
		}
		if plainWindows.MatchString(word) {
			return word, nil
		}
		return `"` + word + `"`, nil
	default:
		if plainWindows.MatchString(word) {
			return word, nil
		}
		return "", errors.New(word + " needs quoting, and this client's Windows hook shell is undocumented; use paths without spaces")
	}
}

// hookCommands is the command line for each event in one client's shell.
func hookCommands(server entry, client, shell string, events ...string) (map[string]string, error) {
	commands := map[string]string{}
	for _, event := range events {
		command, err := shellCommand(server.Binary, shell, hookArgs(server, client, event)...)
		if err != nil {
			return nil, err
		}
		commands[event] = command
	}
	return commands, nil
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
	updated, err := planTOMLBlock(path, text, body)
	if err != nil {
		return err
	}
	return writeAtomic(path, updated)
}

// planTOMLBlock is writeTOMLBlock without the write.
func planTOMLBlock(path, text, body string) ([]byte, error) {
	updated, err := withBlock(text, "#", body)
	if err != nil {
		return nil, errors.New(path + ": " + err.Error())
	}
	if err := toml.Unmarshal([]byte(updated), &map[string]any{}); err != nil {
		return nil, errors.New("Elysian's entries would make " + path + " invalid TOML, so it was left untouched: " + err.Error())
	}
	return []byte(updated), nil
}

// headerPath reads a table header line, [a."b".'c'], as the key path TOML gives it; any other line,
// an array-of-tables header included, is not one.
func headerPath(line string) ([]string, bool) {
	trimmed := strings.TrimSpace(line)
	if !strings.HasPrefix(trimmed, "[") || strings.HasPrefix(trimmed, "[[") {
		return nil, false
	}
	document := map[string]any{}
	if toml.Unmarshal([]byte(trimmed+"\n"), &document) != nil {
		return nil, false
	}
	var path []string
	for node := document; len(node) == 1; {
		for key, value := range node {
			path = append(path, key)
			node, _ = value.(map[string]any)
		}
	}
	return path, len(path) > 0
}

// withoutTables removes every table whose header path starts with prefix, each up to the next header;
// a line inside a multi-line string is text, never a header. Outside those tables the result must
// parse exactly as the original did, or nothing is removed and the reason is returned.
func withoutTables(text string, prefix ...string) (string, error) {
	lines := strings.Split(text, "\n")
	kept := make([]string, 0, len(lines))
	skipping, quote := false, ""
	for _, line := range lines {
		if quote == "" && strings.HasPrefix(strings.TrimSpace(line), "[") {
			path, ok := headerPath(line)
			skipping = ok && len(path) >= len(prefix) && slices.Equal(path[:len(prefix)], prefix)
		}
		quote = multiline(line, quote)
		if !skipping {
			kept = append(kept, line)
		}
	}
	result := strings.Join(kept, "\n")
	before, after := map[string]any{}, map[string]any{}
	if err := toml.Unmarshal([]byte(text), &before); err != nil {
		return "", err
	}
	if err := toml.Unmarshal([]byte(result), &after); err != nil {
		return "", errors.New("removing " + strings.Join(prefix, ".") + " would break the file: " + err.Error())
	}
	drop(before, prefix)
	drop(after, prefix)
	if !reflect.DeepEqual(pruned(before), pruned(after)) {
		return "", errors.New("removing " + strings.Join(prefix, ".") + " would change more than that table")
	}
	return result, nil
}

// multiline returns the multi-line string delimiter still open after line, given the one open before.
func multiline(line, open string) string {
	for i := 0; i+3 <= len(line); {
		switch {
		case open == "" && (line[i:i+3] == `"""` || line[i:i+3] == "\x27\x27\x27"):
			open, i = line[i:i+3], i+3
		case open != "" && line[i:i+3] == open:
			open, i = "", i+3
		case open == "" && line[i] == '#':
			return open
		default:
			i++
		}
	}
	return open
}

// pruned drops empty tables, which hold no value, so an emptied parent compares equal to an absent one.
func pruned(document map[string]any) map[string]any {
	for key, value := range document {
		if table, ok := value.(map[string]any); ok {
			if len(pruned(table)) == 0 {
				delete(document, key)
			}
		}
	}
	return document
}

// drop deletes the value at path from a parsed document.
func drop(document map[string]any, path []string) {
	for _, key := range path[:len(path)-1] {
		next, ok := document[key].(map[string]any)
		if !ok {
			return
		}
		document = next
	}
	delete(document, path[len(path)-1])
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
