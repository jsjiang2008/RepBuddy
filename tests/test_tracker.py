#  Replay small movements with a fake clock to check counting and calibration.
import json
import math
import unittest
from types import SimpleNamespace

from backend.tracker import PushUpTracker, assess_plank, calculate_angle, pose_point


def front_plank():
    # Build visible arms and a level torso without needing any leg points.
    image = [SimpleNamespace(x=0.5, y=0.5, visibility=1.0) for _ in range(25)]
    world = [SimpleNamespace(x=0.0, y=0.0, z=0.0) for _ in range(25)]
    for ids, x in [((11, 13, 15, 23), -0.2), ((12, 14, 16, 24), 0.2)]:
        for index, (y, z) in zip(ids, ((0, -0.5), (0.25, -0.5), (0.5, -0.5), (0, 0))):
            world[index] = SimpleNamespace(x=x, y=y, z=z)
    return image, world


class TrackerTests(unittest.TestCase):
    # Check that observed time and clear body movement control the counter.

    def setUp(self):
        self.now = 0.0
        self.tracker = PushUpTracker(clock=lambda: self.now)
        self.tracker.start()

    def frame(self, angle: float | None = 170, *, right=None, quality='valid', has_pose=True, dt=0.05, now=None):
        # Send one observation and advance the fake clock unless a time is supplied.
        self.now = self.now + dt if now is None else now
        self.tracker.update(angle, angle if right is None else right,
                            quality == 'valid', has_pose, quality=quality,
                            reason=None if quality == 'valid' else 'hips_not_visible')

    def hold(self, angle, *, right=None, frames=4, quality='valid'):
        # Send several fresh frames so a stable endpoint can be confirmed.
        for _ in range(frames):
            self.frame(angle, right=right, quality=quality)

    def down(self):
        # Prepare a partial rep that has reached the bottom.
        self.hold(170)
        self.hold(80)
        self.assertEqual(self.tracker.stage, 'down')

    def test_complete_cycle_and_no_double_count(self):
        # A full movement counts once and staying at the top adds nothing.
        self.down()
        self.hold(170)
        self.hold(170)
        self.assertEqual(self.tracker.counter, 1)

    def test_single_frame_angle_spike_cannot_change_stage(self):
        # A brief false bottom reading cannot arm a rep.
        self.hold(170)
        self.frame(80)
        self.hold(170)
        self.assertEqual(self.tracker.stage, 'up')
        self.assertEqual(self.tracker.counter, 0)

    def test_top_requires_observed_time_and_distinct_timestamps(self):
        # Repeated frames at one time do not satisfy the hold duration.
        self.frame(now=0)
        for _ in range(10):
            self.frame(now=0)
        self.assertIsNone(self.tracker.stage)
        self.frame(now=0.119)
        self.assertIsNone(self.tracker.stage)
        self.frame(now=0.12)
        self.assertEqual(self.tracker.stage, 'up')

    def test_small_jitter_keeps_a_hold_but_larger_motion_breaks_it(self):
        # Allow slight angle noise after entry while rejecting a moving endpoint.
        self.frame(162, now=0)
        self.frame(158, now=0.06)
        self.frame(157, now=0.13)
        self.assertEqual(self.tracker.stage, 'up')
        self.frame(89)
        self.frame(95)
        self.hold(105)
        self.assertEqual(self.tracker.stage, 'up')

    def test_both_arms_must_reach_the_endpoint(self):
        # One straight arm or one bent arm cannot establish both endpoints.
        self.hold(170, right=120)
        self.assertIsNone(self.tracker.stage)
        self.hold(170)
        self.hold(80, right=120)
        self.assertEqual(self.tracker.stage, 'up')

    def test_short_dropout_preserves_rep_but_recovery_needs_a_fresh_hold(self):
        # Unclear frames preserve the last stage without completing a rep.
        self.down()
        self.frame(170, quality='uncertain')
        self.frame(170, quality='uncertain', dt=0.15)
        self.assertEqual(self.tracker.counter, 0)
        self.assertTrue(self.tracker.snapshot()['inGracePeriod'])
        self.frame(170)
        self.assertEqual(self.tracker.counter, 0)
        self.hold(170)
        self.assertEqual(self.tracker.counter, 1)
        self.assertFalse(self.tracker.snapshot()['inGracePeriod'])

    def test_long_dropout_invalidates_even_when_next_frame_recovers(self):
        # Recovery after the grace period must start a new movement.
        self.down()
        self.frame(float('nan'), quality='uncertain', has_pose=False)
        lost_at = self.now
        self.frame(170, quality='uncertain', now=lost_at + 0.25)
        self.frame(170, now=lost_at + 0.5)
        self.assertIsNone(self.tracker.stage)
        self.hold(170)
        self.assertEqual(self.tracker.stage, 'up')
        self.assertEqual(self.tracker.counter, 0)

    def test_known_bad_posture_clears_partial_rep_immediately(self):
        # Visible incorrect posture does not receive the uncertainty delay.
        self.down()
        self.frame(170, quality='invalid')
        self.assertIsNone(self.tracker.stage)
        self.assertFalse(self.tracker.snapshot()['inGracePeriod'])
        self.hold(170)
        self.assertEqual(self.tracker.counter, 0)

    def test_missing_pose_or_invalid_angles_never_count(self):
        # Missing and impossible readings cannot complete the return to the top.
        for angle, has_pose in [(float('nan'), True), (float('inf'), True),
                                (181, True), (-1, True), (None, True), (170, False)]:
            with self.subTest(angle=angle, has_pose=has_pose):
                self.tracker.reset()
                self.tracker.start()
                self.down()
                self.frame(angle, has_pose=has_pose)
                self.assertEqual(self.tracker.counter, 0)
                self.assertEqual(self.tracker.tracking_quality, 'uncertain')
                json.dumps(self.tracker.snapshot(), allow_nan=False)

    def test_delayed_frame_cannot_complete_endpoint_or_preserve_an_old_rep(self):
        # Unobserved time adds no hold credit and a long gap discards the rep.
        self.frame(now=0)
        self.frame(now=0.3)
        self.assertIsNone(self.tracker.stage)
        self.hold(170)
        self.hold(80)
        self.frame(170, dt=0.5)
        self.hold(170)
        self.assertEqual(self.tracker.counter, 0)

    def test_backwards_clock_discards_the_partial_movement(self):
        # A restarted replay clock cannot finish a movement from an older time.
        self.down()
        self.frame(170, now=0)
        self.hold(170)
        self.assertEqual(self.tracker.counter, 0)

    def test_pause_freezes_time_and_invalidates_partial_rep(self):
        # Paused time is excluded and a resumed set requires a fresh plank.
        self.down()
        self.now = 2
        self.tracker.pause()
        self.now = 20
        self.hold(170)
        self.assertEqual(self.tracker.snapshot()['elapsedSeconds'], 2)
        self.assertEqual(self.tracker.counter, 0)
        self.tracker.start()
        self.hold(170)
        self.assertEqual(self.tracker.counter, 0)

    def test_goal_completion_and_new_set(self):
        # The goal pauses timing and the next start clears completed reps.
        self.tracker.reset()
        self.tracker.set_goal(5)
        self.tracker.start()
        self.hold(170)
        for _ in range(5):
            self.hold(80)
            self.hold(170)
        self.assertTrue(self.tracker.snapshot()['completed'])
        self.assertFalse(self.tracker.running)
        self.tracker.start()
        self.assertEqual(self.tracker.counter, 0)
        self.assertEqual(self.tracker.goal, 5)
        self.assertTrue(self.tracker.running)

    def test_invalid_goals_and_json_serialization(self):
        # Only supported whole number goals are accepted and status is valid JSON.
        for goal in (True, 0, '5', 7):
            with self.assertRaises(ValueError):
                self.tracker.set_goal(goal)
        json.dumps(self.tracker.snapshot(), allow_nan=False)

    def calibrate(self, top=170, bottom=80):
        # Complete the three guided holds using clear and steady observations.
        self.tracker.pause()
        self.tracker.begin_calibration()
        self.hold(top, frames=15)
        self.assertEqual(self.tracker.calibration_state, 'lower')
        self.hold(bottom, frames=9)
        self.assertEqual(self.tracker.calibration_state, 'return_up')
        self.hold(top, frames=9)
        self.assertEqual(self.tracker.calibration_state, 'ready')

    def test_calibration_is_guided_and_does_not_count_or_time_a_workout(self):
        # Learning requires all three positions and does not create workout progress.
        self.calibrate()
        status = self.tracker.snapshot()
        self.assertEqual(status['reps'], 0)
        self.assertEqual(status['elapsedSeconds'], 0)
        self.assertEqual(status['calibrationProgress'], 1)
        self.assertFalse(self.tracker.running)
        self.tracker.start()
        self.hold(170)
        self.hold(80)
        self.hold(170)
        self.assertEqual(self.tracker.counter, 1)

    def test_calibration_cannot_accept_a_shallow_or_unsteady_sample(self):
        # Small movements and moving endpoints cannot teach easier thresholds.
        self.tracker.pause()
        self.tracker.begin_calibration()
        for _ in range(20):
            self.frame(155)
            self.frame(170)
        self.assertEqual(self.tracker.calibration_state, 'hold_up')
        self.hold(150, frames=15)
        self.assertEqual(self.tracker.calibration_state, 'lower')
        self.hold(100, frames=12)
        self.assertEqual(self.tracker.calibration_state, 'lower')
        self.hold(110, frames=12)
        self.assertEqual(self.tracker.calibration_state, 'lower')

    def test_calibration_uncertainty_and_large_time_gaps_restart_the_hold(self):
        # Unclear frames and missing time cannot complete a learned position.
        self.tracker.pause()
        self.tracker.begin_calibration()
        self.hold(170, frames=10)
        self.frame(170, quality='uncertain')
        self.hold(170, frames=5)
        self.assertEqual(self.tracker.calibration_state, 'hold_up')
        self.frame(170, dt=1)
        self.assertEqual(self.tracker.calibration_state, 'hold_up')
        self.hold(170, frames=15)
        self.assertEqual(self.tracker.calibration_state, 'lower')

    def test_calibration_requires_return_and_clamps_learned_angles(self):
        # Learned values stay within movement bounds at either extreme.
        self.calibrate(top=150, bottom=95)
        self.assertEqual(self.tracker._thresholds, ((150, 150), (95, 95)))
        self.calibrate(top=180, bottom=50)
        self.assertEqual(self.tracker._thresholds, ((165, 165), (70, 70)))

    def test_cancel_reset_and_clear_handle_saved_calibration(self):
        # Cancelling and resetting preserve learned values until they are cleared.
        self.calibrate()
        saved = self.tracker._thresholds
        self.tracker.begin_calibration()
        with self.assertRaises(ValueError):
            self.tracker.start()
        self.tracker.cancel_calibration()
        self.assertEqual(self.tracker.calibration_state, 'ready')
        self.assertEqual(self.tracker._thresholds, saved)
        self.tracker.reset()
        self.assertEqual(self.tracker._thresholds, saved)
        self.tracker.clear_calibration()
        self.assertEqual(self.tracker.calibration_state, 'idle')
        self.assertIsNone(self.tracker._thresholds)
        self.tracker.start()
        with self.assertRaises(ValueError):
            self.tracker.begin_calibration()


class PlankGeometryTests(unittest.TestCase):
    # Separate unclear body measurements from clear posture problems.

    def test_front_plank_needs_no_knees_or_ankles(self):
        # Visible torso and arms are enough for a valid front facing plank.
        image, world = front_plank()
        self.assertEqual(assess_plank(image, world).quality, 'valid')

    def test_hidden_required_joints_get_specific_reasons(self):
        # Feedback names the body area that needs to stay in view.
        for index, reason in [(11, 'shoulders_not_visible'), (14, 'elbows_not_visible'),
                              (15, 'wrists_not_visible'), (24, 'hips_not_visible')]:
            with self.subTest(index=index):
                image, world = front_plank()
                image[index].visibility = 0.49
                result = assess_plank(image, world)
                self.assertEqual((result.quality, result.reason), ('uncertain', reason))

    def test_missing_and_broken_coordinates_are_uncertain(self):
        # Absent body points and invalid coordinates produce recoverable uncertainty.
        image, world = front_plank()
        self.assertEqual(assess_plank(None, None).reason, 'no_pose')
        self.assertEqual(assess_plank(image, None).reason, 'world_landmarks_missing')
        self.assertEqual(assess_plank(image[:20], world).reason, 'hips_not_visible')
        image[15].x = 1.1
        self.assertEqual(assess_plank(image, world).reason, 'wrists_not_visible')
        image[15].x = float('nan')
        self.assertEqual(assess_plank(image, world).reason, 'invalid_landmarks')
        image, world = front_plank()
        world[11].z = float('inf')
        self.assertEqual(assess_plank(image, world).reason, 'invalid_landmarks')

    def test_upright_sideways_and_raised_hands_have_distinct_reasons(self):
        # Clear geometry mistakes should immediately invalidate a movement.
        image, world = front_plank()
        for index in (23, 24):
            world[index].y = 1
        self.assertEqual(assess_plank(image, world).reason, 'torso_too_upright')
        image, world = front_plank()
        for point in world:
            point.x, point.z = point.z, -point.x
        self.assertEqual(assess_plank(image, world).reason, 'face_camera')
        image, world = front_plank()
        world[15].y = 0
        self.assertEqual(assess_plank(image, world).reason, 'hands_not_below_shoulders')

    def test_boundary_tilt_is_uncertain_instead_of_definitely_wrong(self):
        # A small tolerance prevents noisy boundary readings from resetting a rep.
        image, world = front_plank()
        for index in (23, 24):
            world[index].y = math.tan(math.radians(34)) * 0.5
        result = assess_plank(image, world)
        self.assertEqual((result.quality, result.reason), ('uncertain', 'borderline_posture'))

    def test_angle_math_rejects_collapsed_or_missing_points(self):
        # Impossible arm segments return a missing angle rather than a false endpoint.
        self.assertEqual(calculate_angle([0, 0, 0], [0, 1, 0], [0, 2, 0]), 180)
        self.assertTrue(math.isnan(calculate_angle([0, 0, 0], [0, 0, 0], [1, 1, 1])))
        self.assertTrue(math.isnan(calculate_angle(pose_point(None, 11), [0, 0, 0], [1, 1, 1])))
