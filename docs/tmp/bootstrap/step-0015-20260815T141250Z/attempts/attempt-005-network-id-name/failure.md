# Attempt 005: Docker network ID/name mismatch

The full runner passed, and the independent checker passed application facts,
History replay, Certificates, final State, removal, and the eight direct
connectivity probes. It rejected the topology join because the proof named the
Compose application network by Docker's short ID while raw inspection named
the same object `safe-change-deathstar-step15_default`.

The runner now resolves the selected network ID to its canonical Docker name
before using or recording it. No isolation assertion or checker condition was
changed.
