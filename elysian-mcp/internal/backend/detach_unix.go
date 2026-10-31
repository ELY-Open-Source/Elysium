//go:build !windows

package backend

import (
	"os/exec"
	"syscall"
)

// detach puts the API in its own session, so it outlives the client that started this server.
func detach(command *exec.Cmd) {
	command.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
}
