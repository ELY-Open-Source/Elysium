//go:build windows

package backend

import (
	"os/exec"
	"syscall"
)

const detachedProcess = 0x00000008

// detach gives the API its own process group and no console, so it outlives the client.
func detach(command *exec.Cmd) {
	command.SysProcAttr = &syscall.SysProcAttr{CreationFlags: syscall.CREATE_NEW_PROCESS_GROUP | detachedProcess}
}
