package config

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
)

// oldEnvPrefixes are the names before Elysian; a variable under one would be ignored.
var oldEnvPrefixes = []string{"ELY_EYE_", "ELYSIUM_"}

type Config struct {
	ProjectRoot string `json:"project_root"`
	ElysianHome string `json:"elysian_home"`
	Database    string `json:"database"`
	Binary      string `json:"binary"`
	APIBaseURL  string `json:"api_base_url"`
}

// Resolve locates the Elysian data home and its SQLite database. Reads mirror
// any local .elysian store directly, so identity is anchored on the database
// itself rather than on Elysian repository layout. This lets the MCP server be
// deployed for any project that owns an .elysian/data/elysian.sqlite. Writes go
// through the Elysian API, which owns the memory rules.
func Resolve(projectRoot string, elysianHome string, binary string) (Config, error) {
	if err := refuseOldNames(os.Environ()); err != nil {
		return Config{}, err
	}
	home, err := resolveHome(projectRoot, elysianHome)
	if err != nil {
		return Config{}, err
	}
	db := filepath.Join(home, "data", "elysian.sqlite")
	if _, err := os.Stat(db); err != nil {
		return Config{}, errors.New("Elysian database is required at " + db)
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
		ElysianHome: home,
		Database:    db,
		Binary:      binary,
		APIBaseURL:  apiBaseURL(),
	}, nil
}

// apiBaseURL points at the Elysian API that owns every write rule.
func apiBaseURL() string {
	if fromEnv := os.Getenv("ELYSIAN_API"); fromEnv != "" {
		return fromEnv
	}
	return "http://127.0.0.1:8765"
}

func resolveHome(projectRoot string, elysianHome string) (string, error) {
	if elysianHome == "" {
		elysianHome = os.Getenv("ELYSIAN_HOME")
	}
	if elysianHome != "" {
		return filepath.Abs(elysianHome)
	}
	if projectRoot != "" {
		abs, err := filepath.Abs(projectRoot)
		if err != nil {
			return "", err
		}
		return filepath.Join(abs, ".elysian"), nil
	}
	return discoverHome()
}

func discoverHome() (string, error) {
	current, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		home := filepath.Join(current, ".elysian")
		if _, err := os.Stat(filepath.Join(home, "data", "elysian.sqlite")); err == nil {
			return home, nil
		}
		next := filepath.Dir(current)
		if next == current {
			return "", errors.New("cannot find an Elysian data home; pass --elysian-home or set ELYSIAN_HOME")
		}
		current = next
	}
}

// refuseOldNames stops on any old-prefix variable: ignoring ELYSIUM_AUTH_TOKEN would
// send every read and write without the caller's token.
func refuseOldNames(environment []string) error {
	for _, entry := range environment {
		name, _, _ := strings.Cut(entry, "=")
		for _, prefix := range oldEnvPrefixes {
			if strings.HasPrefix(name, prefix) {
				return errors.New(name + " is set, but this project is now Elysian and reads ELYSIAN_" +
					strings.TrimPrefix(name, prefix) + "; rename every " + prefix + "* variable")
			}
		}
	}
	return nil
}
