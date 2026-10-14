CREATE TABLE workouts (
    id UUID PRIMARY KEY,
    completed_at TIMESTAMPTZ NOT NULL,
    reps INTEGER NOT NULL CHECK (reps > 0),
    goal INTEGER NOT NULL CHECK (goal IN (5, 10, 15, 20)),
    duration_seconds DOUBLE PRECISION NOT NULL CHECK (
        duration_seconds >= 0 AND duration_seconds < 'Infinity'::DOUBLE PRECISION
    ),
    CHECK (reps = goal)
);

CREATE INDEX workouts_completed_at_id_idx ON workouts (completed_at DESC, id DESC);
