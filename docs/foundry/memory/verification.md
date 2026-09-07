# Hindsight verification record

Local verification on September 7, 2026, using Python 3.13.14,
`hindsight-strands` 0.1.3 and `hindsight-client` 0.9.2 from `uv.lock`.

- Full suite with the optional integration installed: **567 passed, 1 skipped**.
  The two existing TLS deprecation warnings remain.
- New provider/example suite: **32 passed**, including strict capability validation,
  immutable scopes, model schemas without bank arguments, failures, empty recall,
  Bedrock coexistence, both factory paths, and concurrent client affinity/cleanup.
- Ruff lint/format, basedpyright (zero errors), and the required narrow Bandit
  scan passed. `just` was unavailable locally; its constituent commands were run.
- All four packages built successfully. A fresh environment installed the wheels
  without either Hindsight distribution; normal imports passed and adapter
  construction produced the expected actionable missing-extra error.
- `examples/hindsight_memory.py` used a real local Hindsight service and real model:
  conversation one retained fictional Project Juniper information; conversation
  two began with empty history and recovered `LANTERN-742` through its recall tool.
  The entire process, including client cleanup, exited successfully.
- Four simultaneous official recall calls against two separate fictional banks
  returned each bank's own project code without returning the other's code.
  Caller-owned cleanup completed after concurrent operations.
- A real connection refusal propagated as a tool failure; caller cleanup passed.

The initial live run found that calling the raw client's `aclose()` on the
application loop after tool use failed with a cross-loop exception. The tested
composition example now keeps all official client operations and cleanup on one
caller-owned thread. The adapter still delegates tool creation to the official
integration and does not implement a replacement HTTP client.

Offline tests simulate service behavior; only the explicit live checks above
contacted the service. This record does not establish production authorization,
service-restart durability, production load capacity, remote encryption, or
sensitive-error redaction. Those controls remain deployment review items in the
security checklist. The PR workflow exercises offline checks; it requires no
service credentials and does not claim to perform the live demonstration.
