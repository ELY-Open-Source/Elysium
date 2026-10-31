package setup

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
)

// codexHookHash is the fingerprint Codex stores when a user trusts a hook in /hooks: sha256 of the
// compact, key-sorted JSON of the event, its matcher and the normalized handler (codex-rs
// config/src/fingerprint.rs). Pinning our own command's hash trusts exactly that command, nothing else.
func codexHookHash(eventSnake, matcher, command string, timeout int) (string, error) {
	identity := map[string]any{
		"event_name": eventSnake,
		"hooks":      []any{map[string]any{"type": "command", "command": command, "timeout": timeout, "async": false}},
	}
	if matcher != "" {
		identity["matcher"] = matcher
	}
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(identity); err != nil {
		return "", err
	}
	sum := sha256.Sum256(bytes.TrimRight(buffer.Bytes(), "\n"))
	return "sha256:" + hex.EncodeToString(sum[:]), nil
}
