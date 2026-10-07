package config

import (
	"errors"
	"os"
	"path/filepath"
)

type Config struct {
	ProjectRoot string `json:"project_root"`
	ElyEyeHome  string `json:"ely_eye_home"`
	Database    string `json:"database"`
	Binary      string `json:"binary"`
	APIBaseURL  string `json:"api_base_url"`
}

// Resolve locates the Ely-Eye data home and its SQLite database. Reads mirror
// any local .ely_eye store directly, so identity is anchored on the database
// itself rather than on Ely-Eye repository layout. This lets the MCP server be
// deployed for any project that owns an .ely_eye/data/ely_eye.sqlite. Writes go
// through the Ely-Eye API, which owns the memory rules.
func Resolve(projectRoot string, elyEyeHome string, binary string) (Config, error) {
	home, err := resolveHome(projectRoot, elyEyeHome)
	if err != nil {
		return Config{}, err
	}
	db := filepath.Join(home, "data", "ely_eye.sqlite")
	if _, err := os.Stat(db); err != nil {
		return Config{}, errors.New("Ely-Eye database is required at " + db)
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
		ElyEyeHome:  home,
		Database:    db,
		Binary:      binary,
		APIBaseURL:  apiBaseURL(),
	}, nil
}

// apiBaseURL points at the Ely-Eye API that owns every write rule.
func apiBaseURL() string {
	if fromEnv := os.Getenv("ELY_EYE_API"); fromEnv != "" {
		return fromEnv
	}
	return "http://127.0.0.1:8765"
}

func resolveHome(projectRoot string, elyEyeHome string) (string, error) {
	if elyEyeHome == "" {
		elyEyeHome = os.Getenv("ELY_EYE_HOME")
	}
	if elyEyeHome != "" {
		return filepath.Abs(elyEyeHome)
	}
	if projectRoot != "" {
		abs, err := filepath.Abs(projectRoot)
		if err != nil {
			return "", err
		}
		return filepath.Join(abs, ".ely_eye"), nil
	}
	return discoverHome()
}

func discoverHome() (string, error) {
	current, err := os.Getwd()
	if err != nil {
		return "", err
	}
	for {
		home := filepath.Join(current, ".ely_eye")
		if _, err := os.Stat(filepath.Join(home, "data", "ely_eye.sqlite")); err == nil {
			return home, nil
		}
		next := filepath.Dir(current)
		if next == current {
			return "", errors.New("cannot find an Ely-Eye data home; pass --ely-eye-home or set ELY_EYE_HOME")
		}
		current = next
	}
}
