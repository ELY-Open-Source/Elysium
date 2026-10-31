//go:build windows

package backend

import (
	"os/exec"
	"syscall"
)

// createNoWindow gives the API a console no one sees; uv's launcher and its python inherit it, so nothing opens a window.
const createNoWindow = 0x08000000

// detach starts the API in its own process group with a hidden console, so it outlives the client and shows no window.
func detach(command *exec.Cmd) {
	command.SysProcAttr = &syscall.SysProcAttr{CreationFlags: syscall.CREATE_NEW_PROCESS_GROUP | createNoWindow, HideWindow: true}
}
