# Demo recording script (<= 3 min) -> save as demo/walkthrough.mp4
Pre-pull the guest image first (`celesto doctor`, run one throwaway computer) so the first boot is not on camera.
1. (20s) `docker compose up` -> `curl /health`, `/api/runs` shows the seed row.
2. (60s) `python -m grader.cli eval --provider local --runs 1` with a second terminal on `watch celesto computer list`
   (the guest is visible appearing and disappearing). Show `tail -f logs/commands.jsonl`.
3. (50s) `python -m grader.cli containment --provider local` : show a BLOCKED line, the python-urllib bypass failing on network off, rm -rf /work/* then rollback restoring the file.
4. (30s) `python -m grader.cli failure --provider local` : show `policy_applied` in the trace and `celesto computer list` empty at the end.
5. (20s) show `reports/reliability.json` summary and `pytest -q` green.
