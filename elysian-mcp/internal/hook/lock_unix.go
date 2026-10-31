//go:build !windows

package hook

import (
	"os"
	"syscall"
)

// lockFile blocks until this process holds the file exclusively; the kernel frees it if we die.
func lockFile(file *os.File) error { return syscall.Flock(int(file.Fd()), syscall.LOCK_EX) }

func unlockFile(file *os.File) error { return syscall.Flock(int(file.Fd()), syscall.LOCK_UN) }
