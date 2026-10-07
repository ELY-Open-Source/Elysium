package mcpserver

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/ZacharyZhang-NY/ely-eye/ely-eye-mcp/internal/apiclient"
)

const manifestBody = `{"cartridge_id":"home_1","name":"home","created_at":"2026-05-01T12:00:00Z",` +
	`"model_base":"Qwen/Qwen3.5-9B","source_count":1,"atom_count":2,"token_equivalent":40,` +
	`"artifacts":{"atoms":"atoms.parquet"},"dna":"deadbeef",` +
	`"kv_fingerprint":{"format_semver":"1.0.0","rope":{"factor":4.0}}}`

func mountServer(t *testing.T, status int, body string, seen *[]string) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		*seen = append(*seen, r.Method+" "+r.URL.Path)
		w.WriteHeader(status)
		_, _ = w.Write([]byte(body))
	}))
}

func TestMountedCartridgesAsksTheServer(t *testing.T) {
	var seen []string
	server := mountServer(t, http.StatusOK, `{"mounted":["home_1"],"scoped":true,"atoms_in_scope":2}`, &seen)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	_, out, err := s.mountsTool(context.Background(), nil, struct{}{})
	if err != nil {
		t.Fatalf("mounted_cartridges failed: %v", err)
	}
	if !out.State.Scoped || out.State.AtomsInScope != 2 || len(out.State.Mounted) != 1 {
		t.Errorf("mount state = %+v, want the server's scope", out.State)
	}
	if len(seen) != 1 || seen[0] != "GET /api/mounts" {
		t.Errorf("requests = %v, want one GET to /api/mounts", seen)
	}
}

func TestMountCartridgeReturnsTheManifestItMounted(t *testing.T) {
	var seen []string
	server := mountServer(t, http.StatusOK, manifestBody, &seen)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	_, out, err := s.mountTool(context.Background(), nil, CartridgeIDInput{CartridgeID: "home_1"})
	if err != nil {
		t.Fatalf("mount_cartridge failed: %v", err)
	}
	if out.Manifest.CartridgeID != "home_1" || out.Manifest.DNA != "deadbeef" {
		t.Errorf("manifest = %+v, want the mounted cartridge", out.Manifest)
	}
	if out.Manifest.KVFingerprint["rope"] == nil {
		t.Error("manifest lost the kv fingerprint that gated the mount")
	}
	if len(seen) != 1 || seen[0] != "POST /api/cartridges/home_1/mount" {
		t.Errorf("requests = %v, want one POST to the mount route", seen)
	}
}

func TestSwitchAndUnmountUseTheirOwnRoutes(t *testing.T) {
	var seen []string
	server := mountServer(t, http.StatusOK, manifestBody, &seen)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	if _, _, err := s.switchTool(context.Background(), nil, CartridgeIDInput{CartridgeID: "home_1"}); err != nil {
		t.Fatalf("switch_cartridge failed: %v", err)
	}
	if _, _, err := s.unmountTool(context.Background(), nil, CartridgeIDInput{CartridgeID: "home_1"}); err != nil {
		t.Fatalf("unmount_cartridge failed: %v", err)
	}
	want := []string{"POST /api/cartridges/home_1/switch", "POST /api/cartridges/home_1/unmount"}
	if strings.Join(seen, ",") != strings.Join(want, ",") {
		t.Errorf("requests = %v, want %v", seen, want)
	}
}

func TestMountRefusalCarriesTheServersReason(t *testing.T) {
	var seen []string
	server := mountServer(t, http.StatusBadRequest,
		`{"detail":"home_1 was built for a different runtime; refusing to mount: rope: factor: cartridge 4.0 vs local 2.0"}`,
		&seen)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	_, _, err := s.mountTool(context.Background(), nil, CartridgeIDInput{CartridgeID: "home_1"})
	if err == nil {
		t.Fatal("an incompatible cartridge must not mount quietly")
	}
	if !strings.Contains(err.Error(), "rope: factor: cartridge 4.0 vs local 2.0") {
		t.Errorf("error = %v, want the field the server named", err)
	}
}

func TestMountToolsRefuseAnEmptyCartridgeID(t *testing.T) {
	var seen []string
	server := mountServer(t, http.StatusOK, manifestBody, &seen)
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	if _, _, err := s.mountTool(context.Background(), nil, CartridgeIDInput{}); err == nil {
		t.Error("mount without an id must fail before the network")
	}
	if _, _, err := s.switchTool(context.Background(), nil, CartridgeIDInput{}); err == nil {
		t.Error("switch without an id must fail before the network")
	}
	if _, _, err := s.unmountTool(context.Background(), nil, CartridgeIDInput{}); err == nil {
		t.Error("unmount without an id must fail before the network")
	}
	if _, _, err := s.appendTool(context.Background(), nil, AppendInput{CartridgeID: "home_1"}); err == nil {
		t.Error("append without atoms must fail before the network")
	}
	if len(seen) != 0 {
		t.Errorf("requests = %v, want none", seen)
	}
}

func TestAppendSendsTheAtomsItNames(t *testing.T) {
	var seen []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body := make([]byte, 512)
		n, _ := r.Body.Read(body)
		seen = append(seen, r.URL.Path+" "+string(body[:n]))
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(manifestBody))
	}))
	defer server.Close()

	s := &Server{api: apiclient.New(server.URL)}
	_, out, err := s.appendTool(context.Background(), nil, AppendInput{CartridgeID: "home_1", AtomIDs: []string{"mem-1:text"}})
	if err != nil {
		t.Fatalf("append_to_cartridge failed: %v", err)
	}
	if out.Manifest.AtomCount != 2 {
		t.Errorf("manifest = %+v, want the rewritten atom count", out.Manifest)
	}
	if len(seen) != 1 || !strings.Contains(seen[0], "/append") || !strings.Contains(seen[0], "mem-1:text") {
		t.Errorf("requests = %v, want one append carrying the atom id", seen)
	}
}
