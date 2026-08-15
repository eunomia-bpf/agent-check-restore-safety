# Attempt 001: upstream config mode

The run stopped before any experiment condition. The host uses umask `0077`,
so the sparse checkout materialized the upstream `config.json` as mode `0600`.
The pinned frontend image runs as uid 65532 and could not read that bind mount.

No application request was issued. The cleanup trap removed every container,
volume, and network. The runner now normalizes only the regular-file read mode
to `0644`; source bytes, Git tree identities, and upstream commits remain
unchanged.
