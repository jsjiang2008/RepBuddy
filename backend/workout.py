"""Keep track of sets and rest time without counting rest as exercise."""
import math
from typing import Literal


class WorkoutPlan:
    def __init__(self):
        self.total_sets = 1
        self.rest_seconds = 60
        self.reset()

    def reset(self):
        # Keep the chosen settings while clearing progress for a new workout.
        self.state: Literal['idle', 'active', 'resting', 'paused', 'complete'] = 'idle'
        self.current_set = 1
        self.completed_sets = 0
        self.finished_seconds = 0.0
        self.rest_deadline: float | None = None
        self.remaining_rest = 0.0

    def configure(self, sets, rest_seconds):
        # Bound the workout length and reject fractions or text from API callers.
        if type(sets) is not int or not 1 <= sets <= 10:
            raise ValueError('Choose between 1 and 10 sets.')
        if type(rest_seconds) is not int or not 0 <= rest_seconds <= 300:
            raise ValueError('Choose a rest time between 0 and 300 seconds.')
        if self.state != 'idle':
            raise ValueError('Reset the workout before changing its settings.')
        self.total_sets = sets
        self.rest_seconds = rest_seconds

    @property
    def between_sets(self):
        return self.completed_sets == self.current_set and self.completed_sets < self.total_sets

    def rest_remaining(self, now):
        # A paused rest keeps its remaining duration instead of its old deadline.
        return max(0.0, self.rest_deadline - now) if self.rest_deadline is not None else self.remaining_rest

    def start(self, now):
        if self.state == 'complete':
            self.reset()
        if self.between_sets:
            if self.state != 'resting':
                self.rest_deadline = now + self.remaining_rest
            self.state = 'resting'
        else:
            self.state = 'active'

    def pause(self, now):
        if self.state == 'resting':
            self.remaining_rest = self.rest_remaining(now)
            self.rest_deadline = None
        if self.state in ('active', 'resting'):
            self.state = 'paused'

    def finish_set(self, elapsed, now):
        # Count each completed set once, even when saving takes several frames.
        if self.completed_sets >= self.current_set:
            return
        self.completed_sets += 1
        self.finished_seconds += elapsed
        if self.completed_sets == self.total_sets:
            self.state = 'complete'
        else:
            self.state = 'resting'
            self.remaining_rest = float(self.rest_seconds)
            self.rest_deadline = now + self.rest_seconds

    def next_set(self, now, saved):
        # Only advance after rest ends and the previous result is safely saved.
        if self.state != 'resting' or self.rest_remaining(now) > 0 or not saved:
            return False
        self.current_set += 1
        self.remaining_rest = 0.0
        self.rest_deadline = None
        self.state = 'active'
        return True

    def skip_rest(self, now):
        if self.state != 'resting':
            raise ValueError('Resume the rest timer before skipping it.')
        self.rest_deadline = now
        self.remaining_rest = 0.0

    def snapshot(self, now, set_elapsed):
        # Finished time is already included when the current set has completed.
        active_seconds = self.finished_seconds
        if self.completed_sets < self.current_set:
            active_seconds += set_elapsed
        return {
            'totalSets': self.total_sets, 'currentSet': self.current_set,
            'completedSets': self.completed_sets, 'restSeconds': self.rest_seconds,
            'restRemainingSeconds': math.ceil(self.rest_remaining(now)),
            'workoutState': self.state, 'workoutElapsedSeconds': active_seconds,
        }
