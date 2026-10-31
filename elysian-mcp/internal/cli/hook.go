package cli

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/config"
	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/hook"
)

// HookFailed carries the exit code a failed hook must return for its client.
type HookFailed struct {
	Code int
	Err  error
}

func (h HookFailed) Error() string { return h.Err.Error() }

// runHook never lets a memory failure pass unseen: it goes to stderr and ~/.elysian/logs/hook.log.
func runHook(ctx context.Context, args []string) error {
	flags := flag.NewFlagSet("hook", flag.ContinueOnError)
	client := flags.String("client", "", "the coding agent running this hook")
	elysianHome := flags.String("elysian-home", "", "Elysian data home, when setup was given one")
	flags.SetOutput(os.Stderr)
	if err := flags.Parse(args); err != nil {
		return err
	}
	if *client == "" || flags.NArg() != 1 {
		return errors.New("usage: elysian-mcp hook --client <name> <session-start|prompt|approve>")
	}
	cfg, err := config.Resolve("", *elysianHome, "")
	if err == nil {
		err = hook.Run(ctx, cfg, *client, hook.Event(flags.Arg(0)), os.Stdin, os.Stdout)
	}
	if err == nil {
		return nil
	}
	err = fmt.Errorf("elysian %s hook (%s): %w", flags.Arg(0), *client, err)
	logHookFailure(cfg.ElysianHome, err)
	return HookFailed{Code: hook.FailExit(*client), Err: err}
}

func logHookFailure(home string, failure error) {
	if home == "" {
		return
	}
	path := filepath.Join(home, "logs", "hook.log")
	if os.MkdirAll(filepath.Dir(path), 0o700) != nil {
		return
	}
	file, err := os.OpenFile(path, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		return
	}
	defer file.Close()
	fmt.Fprintf(file, "%s %v\n", time.Now().Format(time.RFC3339), failure)
}
