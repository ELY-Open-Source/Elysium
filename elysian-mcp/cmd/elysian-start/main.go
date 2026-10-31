// Command elysian-start makes sure the local Elysian API is running and exits; Windows runs it at sign-in.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/backend"
	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/config"
)

func main() {
	home := flag.String("home", "", "the Elysian home; sign-in does not carry the installer's ELYSIAN_HOME")
	flag.Parse()
	cfg, err := config.Resolve("", *home, "")
	if err == nil {
		err = backend.Ensure(context.Background(), cfg.APIBaseURL, cfg.ElysianHome)
	}
	if err != nil {
		report(cfg.ElysianHome, *home, err)
		os.Exit(1)
	}
}

// report writes the failure where a user can find it: this program has no console to print to.
func report(home string, asked string, err error) {
	if home == "" {
		home = asked
	}
	if home == "" {
		user, homeErr := os.UserHomeDir()
		if homeErr != nil {
			os.Exit(2)
		}
		home = filepath.Join(user, ".elysian")
	}
	path := filepath.Join(home, "logs", "start.log")
	if mkErr := os.MkdirAll(filepath.Dir(path), 0o700); mkErr != nil {
		os.Exit(2)
	}
	file, openErr := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if openErr != nil {
		os.Exit(2)
	}
	defer file.Close()
	fmt.Fprintf(file, "%s elysian-start: %v\n", time.Now().Format(time.RFC3339), err)
}
