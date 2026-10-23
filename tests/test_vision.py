"""Check image processing with a fake pose model and no webcam access."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from backend.vision import PoseProcessor


def pose_result():
    """Create a level torso and straight arms for a clear front facing plank."""
    image = [SimpleNamespace(x=0.5, y=0.5, z=0.0, visibility=1.0) for _ in range(33)]
    world = [SimpleNamespace(x=0.0, y=0.0, z=0.0, visibility=1.0) for _ in range(33)]
    for ids, x in [((11, 13, 15, 23), -0.2), ((12, 14, 16, 24), 0.2)]:
        for index, (y, z) in zip(ids, ((0, -0.5), (0.25, -0.5), (0.5, -0.5), (0, 0))):
            world[index] = SimpleNamespace(x=x, y=y, z=z, visibility=1.0)
    return SimpleNamespace(pose_landmarks=SimpleNamespace(landmark=image),
                           pose_world_landmarks=SimpleNamespace(landmark=world))


class VisionTests(unittest.TestCase):
    """Verify model input, detailed feedback, and the saved replay measurements."""

    def setUp(self):
        self.result = pose_result()
        self.model = Mock()
        self.model.process.return_value = self.result
        factory = patch('backend.vision.Pose', return_value=self.model)
        self.addCleanup(factory.stop)
        factory.start()
        self.processor = PoseProcessor()
        self.addCleanup(self.processor.close)
        self.frame = np.zeros((24, 32, 3), dtype=np.uint8)

    def test_valid_pose_exposes_angles_assessment_and_replay_points(self):
        """Good measurements reach callers while preserving the existing frame result."""
        frame, left, right, plank, has_pose = self.processor.process(self.frame)
        self.assertEqual(frame.shape, self.frame.shape)
        self.assertEqual(frame.dtype, np.uint8)
        self.assertEqual((left, right), (180, 180))
        self.assertTrue(plank)
        self.assertTrue(has_pose)
        self.assertEqual(self.processor.assessment.quality, 'valid')
        self.assertIsNone(self.processor.assessment.reason)
        self.assertIs(self.processor.last_landmarks, self.result.pose_landmarks.landmark)
        self.assertIs(self.processor.last_world_landmarks, self.result.pose_world_landmarks.landmark)

    def test_input_is_mirrored_and_colors_are_converted(self):
        """The model receives the same mirrored view that the user sees."""
        self.frame[1, 2] = [10, 20, 30]
        self.processor.process(self.frame)
        model_input = self.model.process.call_args.args[0]
        np.testing.assert_array_equal(model_input[1, -3], [30, 20, 10])
        np.testing.assert_array_equal(self.frame[1, 2], [10, 20, 30])

    def test_missing_pose_clears_old_replay_points_and_angles(self):
        """A lost body detection cannot reuse measurements from the preceding frame."""
        self.processor.process(self.frame)
        self.model.process.return_value = SimpleNamespace(pose_landmarks=None, pose_world_landmarks=None)
        _, left, right, plank, has_pose = self.processor.process(self.frame)
        self.assertTrue(np.isnan([left, right]).all())
        self.assertFalse(plank)
        self.assertFalse(has_pose)
        self.assertEqual(self.processor.assessment.reason, 'no_pose')
        self.assertIsNone(self.processor.last_landmarks)
        self.assertIsNone(self.processor.last_world_landmarks)

    def test_missing_spatial_points_suspend_counting(self):
        """Image points alone cannot confirm the depth of a front facing plank."""
        self.result.pose_world_landmarks = None
        _, left, right, plank, has_pose = self.processor.process(self.frame)
        self.assertTrue(has_pose)
        self.assertFalse(plank)
        self.assertTrue(np.isnan([left, right]).all())
        self.assertEqual(self.processor.assessment.reason, 'world_landmarks_missing')

    def test_hidden_and_offscreen_joints_are_not_drawn_as_valid(self):
        """Unclear required joints produce specific feedback and no offscreen drawing."""
        self.result.pose_landmarks.landmark[15].x = 2
        self.result.pose_landmarks.landmark[16].visibility = 0.2
        with patch('backend.vision.cv2.circle') as draw:
            _, _, _, plank, _ = self.processor.process(self.frame)
        self.assertFalse(plank)
        self.assertEqual(self.processor.assessment.reason, 'wrists_not_visible')
        self.assertEqual(draw.call_count, 6)

    def test_short_landmark_lists_and_nonfinite_image_points_do_not_crash(self):
        """Malformed model output produces uncertainty instead of breaking the preview."""
        self.result.pose_landmarks.landmark = self.result.pose_landmarks.landmark[:15]
        self.result.pose_landmarks.landmark[11].x = float('nan')
        _, _, _, plank, _ = self.processor.process(self.frame)
        self.assertFalse(plank)
        self.assertEqual(self.processor.assessment.quality, 'uncertain')

    def test_collapsed_elbow_cannot_be_reported_as_clear_tracking(self):
        """A torso may look correct while an unusable elbow measurement blocks counting."""
        points = self.result.pose_world_landmarks.landmark
        points[13] = points[11]
        _, left, _, plank, _ = self.processor.process(self.frame)
        self.assertTrue(np.isnan(left))
        self.assertFalse(plank)
        self.assertEqual(self.processor.assessment.reason, 'invalid_landmarks')

    def test_definite_bad_posture_is_preserved_when_an_angle_is_missing(self):
        """A broken arm measurement must not soften an obvious posture failure."""
        points = self.result.pose_world_landmarks.landmark
        points[13] = points[11]
        points[23].y = points[24].y = 1
        self.processor.process(self.frame)
        self.assertEqual(self.processor.assessment.quality, 'invalid')
        self.assertEqual(self.processor.assessment.reason, 'torso_too_upright')

    def test_close_releases_the_pose_model(self):
        """Closing the processor frees the model resources."""
        self.processor.close()
        self.model.close.assert_called_once()
