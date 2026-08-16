//go:build linux

package agentguest

import "testing"

func TestParseCgroupEventsRequiresUniqueFreezeAndPopulationState(t *testing.T) {
	got, err := parseCgroupEvents("populated 1\nfrozen 0\npressure 0\n")
	if err != nil || !got.populated || got.frozen {
		t.Fatalf("parsed cgroup events = %+v, %v", got, err)
	}
	for _, invalid := range []string{
		"", "populated 1\n", "populated 1\nfrozen 2\n",
		"populated 1\npopulated 0\nfrozen 0\n",
	} {
		if _, err := parseCgroupEvents(invalid); err == nil {
			t.Fatalf("accepted cgroup events %q", invalid)
		}
	}
}
