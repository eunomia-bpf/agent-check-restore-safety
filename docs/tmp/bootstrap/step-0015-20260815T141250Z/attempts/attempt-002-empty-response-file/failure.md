# Attempt 002: zero-byte response capture

This run reached the raw-retry condition. The official application committed
the first reservation, the adapter durably recorded `upstream_ok=true` and
`drop=true`, and then closed the connection without sending HTTP bytes.

On this curl version, `-o` did not create its target for that zero-byte
response. The runner failed while measuring the absent file. Cleanup removed
the complete Compose graph and its Mongo volumes. The fix creates empty
capture files before each request; it does not change the fault or application.
