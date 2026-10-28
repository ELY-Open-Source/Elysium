package config

import (
	"strings"
	"testing"
)

func TestAnOldVariableNamesItsNewSpelling(t *testing.T) {
	err := refuseOldNames([]string{"PATH=/bin", "ELY_EYE_AUTH_TOKEN=secret"})
	if err == nil || !strings.Contains(err.Error(), "reads ELYSIUM_AUTH_TOKEN") {
		t.Fatalf("an old variable must stop the server and name its new spelling, got %v", err)
	}
}

func TestOnlyTheNewNamesPass(t *testing.T) {
	if err := refuseOldNames([]string{"ELYSIUM_AUTH_TOKEN=secret", "HOME=/root"}); err != nil {
		t.Fatalf("the new names must pass, got %v", err)
	}
}
