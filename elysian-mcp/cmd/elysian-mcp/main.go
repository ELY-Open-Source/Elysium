package main

import (
	"context"
	"fmt"
	"os"

	"github.com/ELY-Open-Source/Elysian/elysian-mcp/internal/cli"
)

func main() {
	if err := cli.Run(context.Background(), os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
