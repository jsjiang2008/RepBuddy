"""Check saved recordings and reports without using a webcam."""
import copy
from contextlib import redirect_stdout
import io
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from backend.replay import (
    evaluate_trace, load_trace, main, match_completions, trace_video, validate_trace,
)

FIXTURES = Path(__file__).parent / 'fixtures' / 'tracking'


def body_points(bent=False):
    # These invented points describe a front facing torso and two clear arms.
    image = [dict(x=0.5, y=0.5, z=0.0, visibility=1.0) for _ in range(33)]
    world = [dict(x=0.0, y=0.0, z=0.0) for _ in range(33)]
    for shoulder, elbow, wrist, hip, side in ((11, 13, 15, 23, -1), (12, 14, 16, 24, 1)):
        x = side * 0.2
        world[shoulder] = dict(x=x, y=0.0, z=-0.5)
        world[elbow] = dict(x=x + side * (0.3 if bent else 0.0), y=0.25, z=-0.5)
        world[wrist] = dict(x=x, y=0.5, z=-0.5)
        world[hip] = dict(x=x, y=0.0, z=0.0)
    return image, world


class TraceTests(unittest.TestCase):
    def setUp(self):
        self.trace = load_trace(FIXTURES / 'stable_rep.json')

    def test_synthetic_behaviour_regressions(self):
        # The fixtures check counting rules. They do not measure accuracy on people.
        expected = {
            'stable_rep': 1, 'angle_spike': 0, 'brief_occlusion': 1,
            'long_occlusion': 0, 'invalid_posture': 0,
        }
        for name, total in expected.items():
            with self.subTest(name=name):
                report = evaluate_trace(load_trace(FIXTURES / f'{name}.json'), expected_reps=total)
                self.assertEqual(report['sourceKind'], 'synthetic')
                self.assertEqual(report['countedReps'], total)
                self.assertEqual(report['countDifference'], 0)
                self.assertGreater(report['processingFps'], 0)

    def test_null_reason_roundtrips_and_total_does_not_claim_misses(self):
        for frame in self.trace['frames']:
            frame['reason'] = None
        trace = validate_trace(json.loads(json.dumps(self.trace, allow_nan=False)))
        report = evaluate_trace(trace, expected_reps=2)
        self.assertEqual(report['countDifference'], -1)
        self.assertEqual(report['countComparison'], 'undercount')
        self.assertNotIn('completionMatches', report)

    def test_manual_times_identify_missed_and_extra_completions(self):
        matches = match_completions([0.2, 2.2, 4.2], [0.1, 1.1, 4.1], 0.3)
        self.assertEqual(matches, {'matched': 2, 'missed': 1, 'extra': 1})
        report = evaluate_trace(self.trace, expected_times=[1.0], tolerance=0.05)
        self.assertEqual(report['completionMatches'], {'matched': 1, 'missed': 0, 'extra': 0})
        self.assertEqual(report['expectedReps'], 1)
        self.assertEqual(match_completions([0.9, 1.1], [1.0], 0.2)['extra'], 1)

    def test_manual_labels_must_be_ordered_and_inside_the_recording(self):
        for labels in ([0.5, 0.5], [0.7, 0.1], [-0.1], [2.0], [math.inf], [True]):
            with self.subTest(labels=labels), self.assertRaises(ValueError):
                evaluate_trace(self.trace, expected_times=labels)
        with self.assertRaises(ValueError):
            evaluate_trace(self.trace, expected_times=[1.0], expected_reps=2)
        for tolerance in (-1, math.nan, True):
            with self.subTest(tolerance=tolerance), self.assertRaises(ValueError):
                evaluate_trace(self.trace, tolerance=tolerance)

    def test_loss_and_posture_time_use_the_saved_timeline(self):
        report = evaluate_trace(load_trace(FIXTURES / 'brief_occlusion.json'))
        self.assertEqual(report['trackingLossFrames'], 1)
        self.assertAlmostEqual(report['trackingLossSeconds'], 0.1)
        self.assertAlmostEqual(report['trackingLossRate'], 0.1 / 1.2)
        invalid = evaluate_trace(load_trace(FIXTURES / 'invalid_posture.json'))
        self.assertGreater(invalid['invalidPostureSeconds'], 0)
        self.assertEqual(invalid['trackingLossSeconds'], 0)

    def test_raw_points_override_cached_angles_and_posture(self):
        # A saved result must be checked again after geometry rules change.
        for index, frame in enumerate(self.trace['frames']):
            frame['imageLandmarks'], frame['worldLandmarks'] = body_points(4 <= index < 8)
            frame.update(leftAngle=20, rightAngle=20, quality='invalid', inPlank=False)
        report = evaluate_trace(self.trace)
        self.assertEqual(report['countedReps'], 1)
        self.assertEqual(report['landmarkFrames'], 12)
        self.assertEqual(report['cachedMeasurementFrames'], 0)
        self.assertEqual(report['processingMode'], 'trace_landmark_geometry')
        self.assertEqual(report['invalidPostureSeconds'], 0)
        for frame in self.trace['frames']:
            for index in (23, 24):
                frame['worldLandmarks'][index].update(y=1.0, z=-0.5)
            frame.update(quality='valid', inPlank=True)
        standing = evaluate_trace(self.trace)
        self.assertEqual(standing['countedReps'], 0)
        self.assertAlmostEqual(standing['invalidPostureSeconds'], standing['durationSeconds'])

    def test_hidden_joint_in_raw_points_is_uncertain(self):
        for frame in self.trace['frames']:
            frame['imageLandmarks'], frame['worldLandmarks'] = body_points()
            frame['imageLandmarks'][15]['visibility'] = 0.1
        report = evaluate_trace(self.trace)
        self.assertEqual(report['countedReps'], 0)
        self.assertEqual(report['trackingLossRate'], 1)

    def test_malformed_values_and_time_order_are_rejected(self):
        mutations = [
            lambda data: data.update(version=True),
            lambda data: data.update(frames=[]),
            lambda data: data['source'].update(kind=[]),
            lambda data: data['source'].update(fps=0),
            lambda data: data['frames'][0].update(timestamp=-1),
            lambda data: data['frames'][1].update(timestamp=0),
            lambda data: data['frames'][0].update(timestamp=math.inf),
            lambda data: data['frames'][0].update(leftAngle=math.nan),
            lambda data: data['frames'][0].update(rightAngle=181),
            lambda data: data['frames'][0].update(hasPose=1),
            lambda data: data['frames'][0].update(quality=[]),
            lambda data: data['frames'][0].update(reason=''),
            lambda data: data['frames'][0].update(imageLandmarks=[{}]),
        ]
        for mutation in mutations:
            data = copy.deepcopy(self.trace)
            mutation(data)
            with self.subTest(data=data), self.assertRaises(ValueError):
                validate_trace(data)
        points, _ = body_points()
        points[0]['z'] = math.inf
        self.trace['frames'][0]['imageLandmarks'] = points
        with self.assertRaises(ValueError):
            validate_trace(self.trace)

    def test_bad_json_and_nonfinite_json_numbers_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'trace.json'
            for text in ('{broken', '{"version": NaN}', '{"version": Infinity}'):
                path.write_text(text, encoding='utf-8')
                with self.subTest(text=text), self.assertRaises(ValueError):
                    load_trace(path)

    def test_command_exports_a_trace_and_prints_a_report(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'export.json'
            output = io.StringIO()
            with redirect_stdout(output):
                result = main([str(FIXTURES / 'stable_rep.json'), '--expected-reps', '1', '--export', str(target)])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(output.getvalue())['countedReps'], 1)
            self.assertEqual(load_trace(target), self.trace)


class VideoTests(unittest.TestCase):
    def make_video_tools(self, fps=30):
        # Fake video tools verify file handling without reading a camera or loading a model.
        capture = Mock()
        capture.isOpened.return_value = True
        capture.get.return_value = fps
        capture.read.side_effect = [(True, object()), (True, object()), (False, None)]
        processor = Mock()
        processor.process.return_value = (object(), 180.0, 180.0, True, True)
        processor.assessment = SimpleNamespace(quality='valid', reason=None)
        image, world = body_points()
        processor.last_landmarks = [SimpleNamespace(**point) for point in image]
        processor.last_world_landmarks = [SimpleNamespace(**point) for point in world]
        cv2 = SimpleNamespace(VideoCapture=Mock(return_value=capture), CAP_PROP_FPS=5)
        vision = SimpleNamespace(PoseProcessor=Mock(return_value=processor))
        return capture, processor, cv2, vision

    def test_recorded_fps_sets_timestamps_and_raw_points_are_exported(self):
        capture, processor, cv2, vision = self.make_video_tools()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'recording.mp4'
            path.touch()
            with patch.dict('sys.modules', {'cv2': cv2, 'backend.vision': vision}):
                trace, duration = trace_video(path)
            cv2.VideoCapture.assert_called_once_with(str(path.resolve()))
        self.assertGreaterEqual(duration, 0)
        self.assertEqual([frame['timestamp'] for frame in trace['frames']], [0, 1 / 30])
        self.assertEqual(len(trace['frames'][0]['worldLandmarks']), 33)
        self.assertIsNone(trace['frames'][0]['reason'])
        self.assertEqual(validate_trace(json.loads(json.dumps(trace))), trace)
        capture.release.assert_called_once()
        processor.close.assert_called_once()

    def test_invalid_video_metadata_and_empty_video_release_the_file(self):
        for fps in (0, math.nan, math.inf, -1):
            capture, processor, cv2, vision = self.make_video_tools(fps)
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'recording.mp4'
                path.touch()
                with patch.dict('sys.modules', {'cv2': cv2, 'backend.vision': vision}):
                    with self.subTest(fps=fps), self.assertRaises(ValueError):
                        trace_video(path)
            capture.release.assert_called_once()
            vision.PoseProcessor.assert_not_called()
        capture, processor, cv2, vision = self.make_video_tools()
        capture.read.side_effect = [(False, None)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'empty.mp4'
            path.touch()
            with patch.dict('sys.modules', {'cv2': cv2, 'backend.vision': vision}):
                with self.assertRaises(ValueError):
                    trace_video(path)
        capture.release.assert_called_once()
        processor.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
