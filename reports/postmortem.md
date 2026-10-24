# Failure post-mortem

> SIMULATED guest: in-memory fake, no Celesto involved, costs are estimates. Re-run with --provider local|cloud to replace with real measurements.

**15/20 runs succeeded (75%).** Median wall-clock 2.78s, p90 3.14s, median boot-to-ready 0.64s, total cost $0.0003.

A run counts as success only when the proof output (`/work/grade.json`) was read back from the guest AND its score/verdict equals the known-correct grade for that submission. Hostile submissions (infinite loop, file snooping, syntax error) are therefore *expected* to be graded low, and the grader surviving them counts as success. Failed rows are never removed.

## Failed runs
- `sbx-kxw8vge7s7` fixture `wrong_logic`: step 7; `harness exited 137: simulated: harness killed (OOM-ish flake)`; policy applied: rollback
- `sbx-5geheo80jx` fixture `infinite_loop`: step None; `ProviderError: simulated: guest did not become reachable (boot flake)`; policy applied: none (failure was before step 7)
- `sbx-hel8rko85v` fixture `correct_a`: step None; `ProviderError: simulated: guest did not become reachable (boot flake)`; policy applied: none (failure was before step 7)
- `sbx-8qnrxrv6o5` fixture `wrong_logic`: step None; `ProviderError: simulated: guest did not become reachable (boot flake)`; policy applied: none (failure was before step 7)
- `sbx-2fp9eymja5` fixture `infinite_loop`: step 7; `harness exited 137: simulated: harness killed (OOM-ish flake)`; policy applied: rollback

## Root-cause grouping
- step 7: 2 run(s)
- boot/transport failure before Ready: 3 run(s)

Boot failures have no recovery policy by design (nothing to resume or roll back to); a retry wrapper at the job level would fix them at the price of a second boot. Boot-to-ready for those rows is the time burned before the failure, not a successful readiness time.

## Recovery at step 7
0 run(s) hit a step-7 failure and were saved by the `rollback` policy and one retry.
