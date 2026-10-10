"""Stage-boundary fault-injection suite (program sec9/sec23).

Each domain pipeline is exercised boundary-by-boundary (receive -> normalize ->
persist -> publish -> materialize -> reconcile). A fault is injected AFTER the
prior boundary succeeded but BEFORE the next boundary commits; the test then
asserts deterministic recovery:

  * no duplication of authoritative records (idempotent replay collapses),
  * no skip (the failed unit is retried/replayed, never silently dropped),
  * no fabricated success (the checkpoint / stage machine / FSM only advances
    after the durable write actually lands).

The suite shares ``faultkit`` from ``tests/adversarial/`` — one fault
vocabulary across every capability.
"""
