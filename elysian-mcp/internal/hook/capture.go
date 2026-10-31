package hook

import (
	"regexp"
	"strings"
	"unicode/utf8"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/domain"
)

const (
	// minRunes skips "ok", "yes", "继续": a reply, not a statement worth keeping.
	minRunes = 6
	// questionRunes is the length under which a prompt ending in a question mark is only a question.
	questionRunes = 120
	// maxRunes keeps one memory to a statement, not a pasted file.
	maxRunes = 4000
	// recallRunes is how much of one memory goes into the agent's context.
	recallRunes = 400
	// recallBudget stays well under the smallest client cap on injected text (10,000 characters).
	recallBudget = 3000
)

// secretKeys name a field whose value is a credential, whatever its length or punctuation.
const secretKeys = `token|password|passwd|secret|api[_-]?key|access[_-]?key|private[_-]?key`

// secrets are credentials a user may paste; they are masked before anything is stored.
var secrets = []*regexp.Regexp{
	regexp.MustCompile(`-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----`),
	regexp.MustCompile(`\b(sk|rk|pk)-[A-Za-z0-9_\-]{16,}`),
	regexp.MustCompile(`\b(ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}`),
	regexp.MustCompile(`\bxox[abprs]-[A-Za-z0-9\-]{10,}`),
	regexp.MustCompile(`\bAKIA[0-9A-Z]{16}\b`),
	regexp.MustCompile(`\bAIza[0-9A-Za-z_\-]{35}\b`),
	regexp.MustCompile(`(?i)\bbearer\s+[^\s"',}]{8,}`),
	regexp.MustCompile(`(?i)\b[\w-]*(` + secretKeys + `)[\w-]*["']?\s*[:=]\s*"(?:[^"\\]|\\.)*"`),
	regexp.MustCompile(`(?i)\b[\w-]*(` + secretKeys + `)[\w-]*["']?\s*[:=]\s*'(?:[^'\\]|\\.)*'`),
	regexp.MustCompile(`(?i)\b[\w-]*(` + secretKeys + `)[\w-]*["']?\s*[:=]\s*[^\s"']\S*`),
}

// capturable returns the prompt as it will be stored, or false for a command, a one-word reply,
// or a short question: a question asks for memory, it does not state one.
func capturable(prompt string) (string, bool) {
	text := strings.TrimSpace(prompt)
	runes := utf8.RuneCountInString(text)
	if strings.HasPrefix(text, "/") || strings.HasPrefix(text, "!") || runes < minRunes {
		return "", false
	}
	if runes < questionRunes && (strings.HasSuffix(text, "?") || strings.HasSuffix(text, "？")) {
		return "", false
	}
	for _, pattern := range secrets {
		text = pattern.ReplaceAllString(text, "[redacted]")
	}
	return clip(text, maxRunes), true
}

// recall lists hits one per line, newest first as ranked, skipping the prompt's own text.
func recall(hits []domain.AtomHit, prompt string) string {
	var lines []string
	used := 0
	for _, hit := range hits {
		text := strings.TrimSpace(hit.Atom.Text)
		if text == "" || text == strings.TrimSpace(prompt) {
			continue
		}
		line := "- [" + stamp(hit.Atom) + "] " + strings.Join(strings.Fields(clip(text, recallRunes)), " ")
		if used+len(line) > recallBudget {
			break
		}
		lines = append(lines, line)
		used += len(line) + 1
	}
	return strings.Join(lines, "\n")
}

func stamp(atom domain.Atom) string {
	day := atom.IngestedAt
	if len(day) >= 10 {
		day = day[:10]
	}
	if atom.Scenario != "" {
		return day + " · " + atom.Scenario
	}
	return day
}

func clip(text string, limit int) string {
	if utf8.RuneCountInString(text) <= limit {
		return text
	}
	return string([]rune(text)[:limit]) + "…"
}
