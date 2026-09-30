import json
import unittest
from types import SimpleNamespace

from backend.tracker import PushUpTracker, isInPlank


class TrackerTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.tracker = PushUpTracker(clock=lambda: self.now)
        self.tracker.start()

    def frame(self, angle, valid=True, has_pose=True, now=None):
        if now is not None:
            self.now = now
        self.tracker.update(angle, angle, valid, has_pose)

    def test_complete_cycle_and_no_double_count(self):
        for angle in (170, 80, 170, 170):
            self.frame(angle)
        self.assertEqual(self.tracker.counter, 1)

    def test_short_dropout_preserves_rep_without_counting_invalid_frames(self):
        self.frame(170)
        self.frame(80)
        self.frame(170, valid=False, now=1)
        self.assertEqual(self.tracker.counter, 0)
        self.assertTrue(self.tracker.snapshot()['inGracePeriod'])
        self.frame(170, now=1.49)
        self.assertEqual(self.tracker.counter, 1)

    def test_long_dropout_invalidates_even_when_next_frame_recovers(self):
        self.frame(170)
        self.frame(80)
        self.frame(float('nan'), False, False, now=1)
        self.frame(170, now=1.5)
        self.assertEqual(self.tracker.counter, 0)
        self.assertEqual(self.tracker.stage, 'up')

    def test_pause_freezes_time_and_invalidates_partial_rep(self):
        self.frame(170)
        self.frame(80)
        self.now = 2
        self.tracker.pause()
        self.now = 20
        self.frame(170)
        self.assertEqual(self.tracker.snapshot()['elapsedSeconds'], 2)
        self.assertEqual(self.tracker.counter, 0)
        self.tracker.start()
        self.frame(170)
        self.assertEqual(self.tracker.counter, 0)

    def test_goal_completion_and_new_set(self):
        self.tracker.reset()
        self.tracker.set_goal(5)
        self.tracker.start()
        for _ in range(5):
            for angle in (170, 80, 170):
                self.frame(angle)
        self.assertTrue(self.tracker.snapshot()['completed'])
        self.assertFalse(self.tracker.running)
        self.tracker.start()
        self.assertEqual(self.tracker.counter, 0)
        self.assertEqual(self.tracker.goal, 5)
        self.assertTrue(self.tracker.running)

    def test_invalid_goals_and_json_serialization(self):
        for goal in (True, 0, '5', 7):
            with self.assertRaises(ValueError):
                self.tracker.set_goal(goal)
        json.dumps(self.tracker.snapshot(), allow_nan=False)

    def test_front_plank_needs_no_knees_or_ankles_and_rejects_standing_side(self):
        image = [SimpleNamespace(x=0.5, y=0.5, visibility=1) for _ in range(25)]
        world = [SimpleNamespace(x=0, y=0, z=0) for _ in range(25)]
        for ids, x in [((11, 15, 23), -0.2), ((12, 16, 24), 0.2)]:
            for index, (y, z) in zip(ids, ((0, -0.5), (0.5, -0.5), (0, 0))):
                world[index] = SimpleNamespace(x=x, y=y, z=z)
        self.assertTrue(isInPlank(image, world))
        for p in world:
            p.x, p.z = p.z, -p.x
        self.assertFalse(isInPlank(image, world))
        for p in world:
            p.x, p.y = p.y, p.x
        self.assertFalse(isInPlank(image, world))
