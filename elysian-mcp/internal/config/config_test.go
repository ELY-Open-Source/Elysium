package config

import (
	"strings"
	"testing"
)

func TestAnOldVariableNamesItsNewSpelling(t *testing.T) {
	for _, old := range []string{"ELY_EYE_AUTH_TOKEN", "ELYSIUM_AUTH_TOKEN"} {
		err := refuseOldNames([]string{"PATH=/bin", old + "=secret"})
		if err == nil || !strings.Contains(err.Error(), old+" is set") || !strings.Contains(err.Error(), "reads ELYSIAN_AUTH_TOKEN") {
			t.Fatalf("%s must stop the server and name its new spelling, got %v", old, err)
		}
	}
}

func TestOnlyTheNewNamesPass(t *testing.T) {
	if err := refuseOldNames([]string{"ELYSIAN_AUTH_TOKEN=secret", "HOME=/root"}); err != nil {
		t.Fatalf("the new names must pass, got %v", err)
	}
}
