-- Loaded automatically on first boot of the ledger container (mounted at /docker-entrypoint-initdb.d).
-- Idempotent: re-running does not duplicate rows.
CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    sandbox_name     TEXT NOT NULL CHECK (sandbox_name ~ '^sbx-[a-z0-9]{8,}$'),
    problem_id       TEXT NOT NULL,
    state            TEXT NOT NULL CHECK (state IN ('created','ready','running','succeeded','failed','deleted')),
    execution_target TEXT NOT NULL CHECK (execution_target = 'celesto_sandbox'),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO runs (run_id, sandbox_name, problem_id, state, execution_target)
VALUES ('run-seeddemo1', 'sbx-seeddemo1', 'hostile-submission-autograder', 'deleted', 'celesto_sandbox')
ON CONFLICT (run_id) DO NOTHING;
