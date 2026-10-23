"""Check workout progress and rest timing without a camera or real delays."""
import unittest

from backend.workout import WorkoutPlan


class WorkoutPlanTests(unittest.TestCase):
    def test_multiple_sets_finish_without_rest_after_the_last_set(self):
        plan = WorkoutPlan()
        plan.configure(2, 30)
        plan.start(0)
        plan.finish_set(12, 12)
        self.assertEqual(plan.state, 'resting')
        self.assertEqual(plan.snapshot(22, 12)['workoutElapsedSeconds'], 12)
        self.assertFalse(plan.next_set(41.9, True))
        self.assertTrue(plan.next_set(42, True))
        self.assertFalse(plan.next_set(42, True))
        self.assertEqual(plan.current_set, 2)
        plan.finish_set(15, 62)
        self.assertEqual(plan.state, 'complete')
        self.assertEqual(plan.snapshot(100, 15)['workoutElapsedSeconds'], 27)
        self.assertEqual(plan.rest_remaining(100), 0)
        plan.finish_set(15, 100)
        self.assertEqual(plan.completed_sets, 2)
        self.assertEqual(plan.finished_seconds, 27)

    def test_pause_freezes_rest_and_resume_preserves_remaining_time(self):
        plan = WorkoutPlan()
        plan.configure(3, 60)
        plan.start(0)
        plan.finish_set(10, 10)
        plan.pause(30)
        self.assertEqual(plan.rest_remaining(900), 40)
        self.assertFalse(plan.next_set(900, True))
        plan.start(900)
        plan.start(910)
        self.assertEqual(plan.rest_remaining(910), 30)
        self.assertTrue(plan.next_set(940, True))

    def test_skip_and_zero_rest_still_wait_for_saved_results(self):
        for rest in (0, 60):
            with self.subTest(rest=rest):
                plan = WorkoutPlan()
                plan.configure(2, rest)
                plan.start(0)
                plan.finish_set(10, 10)
                plan.skip_rest(10)
                self.assertFalse(plan.next_set(10, False))
                self.assertEqual(plan.current_set, 1)
                self.assertTrue(plan.next_set(10, True))

    def test_single_set_and_new_workout_keep_settings(self):
        plan = WorkoutPlan()
        plan.start(0)
        plan.finish_set(10, 10)
        self.assertEqual(plan.state, 'complete')
        plan.start(20)
        self.assertEqual(plan.state, 'active')
        self.assertEqual(plan.completed_sets, 0)
        plan.reset()
        plan.configure(4, 90)
        plan.reset()
        self.assertEqual((plan.total_sets, plan.rest_seconds), (4, 90))

    def test_invalid_settings_do_not_change_the_plan(self):
        plan = WorkoutPlan()
        for sets, rest in ((0, 60), (11, 60), (True, 60), ('3', 60), (1.5, 60),
                           (2, -1), (2, 301), (2, True), (2, '60'), (2, 0.5), (None, None)):
            with self.subTest(sets=sets, rest=rest), self.assertRaises(ValueError):
                plan.configure(sets, rest)
        self.assertEqual((plan.total_sets, plan.rest_seconds), (1, 60))
        plan.start(0)
        with self.assertRaises(ValueError):
            plan.configure(2, 30)
        plan.pause(1)
        with self.assertRaises(ValueError):
            plan.configure(2, 30)
        with self.assertRaises(ValueError):
            plan.skip_rest(1)

    def test_pausing_active_set_does_not_start_a_rest(self):
        plan = WorkoutPlan()
        plan.configure(2, 60)
        plan.start(0)
        plan.pause(5)
        plan.start(50)
        self.assertEqual(plan.state, 'active')
        self.assertFalse(plan.between_sets)
        self.assertEqual(plan.snapshot(50, 5)['workoutElapsedSeconds'], 5)
