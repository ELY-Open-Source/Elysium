package config

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
)

// oldEnvPrefix is the prefix from before the rename to Elysium; a variable under it would be ignored.
const oldEnvPrefix = "ELY_EYE_"

type Config struct {
	ProjectRoot string `json:"project_root"`
	ElysiumHome string `json:"elysium_home"`
	Database    string `json:"database"`
	Binary      string `json:"binary"`
	APIBaseURL  string `json:"api_base_url"`
}

// Resolve locates the Elysium data home and its SQLite database. Reads mirror
// any local .elysium store directly, so identity is anchored on the database
// itself rather than on Elysium repository layout. This lets the MCP server be
// deployed for any project that owns an .elysium/data/elysium.sqlite. Writes go
// through the Elysium API, which owns the memory rules.
func Resolve(projectRoot string, elysiumHome string, binary string) (Config, error) {
	if err := refuseOldNames(os.Environ()); err != nil {
		return Config{}, err
	}
	home, err := resolveHome(projectRoot, elysiumHome)
	if err != nil {
		return Config{}, err
	}
	db := filepath.Join(home, "data", "elysium.sqlite")
	if _, err := os.Stat(db); err != nil {
		return Config{}, errors.New("Elysium database is required at " + db)
	}
	root := projectRoot
	if root == "" {
		root = filepath.Dir(home)
	}
	root, err = filepath.Abs(root)
	if err != nil {
		return Config{}, err
	}
	if binary == "" {
		binary, _ = os.Executable()
	}
	if binary != "" {
		binary, err = filepath.Abs(binary)
		if err != nil {
			return Config{}, err
		}
	}
	return Config{
		ProjectRoot: root,
		ElysiumHome: home,
		Database:    db,
		Binary:      binary,
		APIBaseURL:  apiBaseURL(),
	}, nil
}

// apiBaseURL points at the Elysium API that owns every write rule.
func apiBaseURL() string {
	if fromEnv := os.Getenv("ELYSIUM_API"); fromEnv != "" {
		return fromEnv
	}
	return "http://127.0.0.1:8765"
}

func resolveHome(projectRoot string, elysiumHome string) (string, error) {
	if elysiumHome == "" {
		elysiumHome = os.Getenv("ELYSIUM_HOME")
	}
	if elysiumHome != "" {
		return filepath.Abs(elysiumHome)
	}
	if projectRoot != "" {
		abs, err := filepath.Abs(projectRoot)
		if err != nil {
			return "", err
		}
		return filepath.Join(abs, ".elysium"), nil
	}
	return discoverHome()
}

func discoverHome() (string, error) {
	current, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		home := filepath.Join(current, ".elysium")
		if _, err := os.Stat(filepath.Join(home, "data", "elysium.sqlite")); err == nil {
			return home, nil
		}
		next := filepath.Dir(current)
		if next == current {
			return "", errors.New("cannot find an Elysium data home; pass --elysium-home or set ELYSIUM_HOME")
		}
		current = next
	}
}

// refuseOldNames stops on any ELY_EYE_* variable: ignoring ELY_EYE_AUTH_TOKEN would
// send every read and write without the caller's token.
func refuseOldNames(environment []string) error {
	for _, entry := range environment {
		name, _, _ := strings.Cut(entry, "=")
		if strings.HasPrefix(name, oldEnvPrefix) {
			return errors.New(name + " is set, but this project is now Elysium and reads ELYSIUM_" +
				strings.TrimPrefix(name, oldEnvPrefix) + "; rename every ELY_EYE_* variable")
		}
	}
	return nil
}
