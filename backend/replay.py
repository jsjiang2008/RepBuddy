"""Evaluate local video files or saved tracking traces without opening a webcam."""
from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
import math
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Any

from .tracker import PushUpTracker, assessPlank, calculateAngle, posePoint

TRACE_VERSION = 1
QUALITIES = {'valid', 'uncertain', 'invalid'}


def _number(value: Any, label: str, *, minimum: float = 0) -> float:
    # Reject missing values and impossible numbers before replay starts.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{label} must be a number.')
    if not math.isfinite(value) or value < minimum:
        raise ValueError(f'{label} must be finite and at least {minimum}.')
    return float(value)


def _angle(value: Any, label: str) -> float | None:
    if value is None:
        return None
    angle = _number(value, label)
    if angle > 180:
        raise ValueError(f'{label} must be between 0 and 180, or null.')
    return angle


def _landmarks(value: Any, label: str) -> list[dict[str, float]] | None:
    # A pose has 33 points. Each point stores its location and optional confidence.
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 33:
        raise ValueError(f'{label} must contain 33 landmarks, or be null.')
    clean = []
    for index, point in enumerate(value):
        if not isinstance(point, dict):
            raise ValueError(f'{label}[{index}] must be an object.')
        coordinates = {
            axis: _number(point.get(axis), f'{label}[{index}].{axis}', minimum=-math.inf)
            for axis in ('x', 'y', 'z')
        }
        for field in ('visibility', 'presence'):
            if field in point:
                score = _number(point[field], f'{label}[{index}].{field}')
                if score > 1:
                    raise ValueError(f'{label}[{index}].{field} must be between 0 and 1.')
                coordinates[field] = score
        clean.append(coordinates)
    return clean


def validate_trace(data: Any) -> dict[str, Any]:
    """Validate untrusted JSON before it can change the tracker clock."""
    if not isinstance(data, dict) or type(data.get('version')) is not int or data['version'] != TRACE_VERSION:
        raise ValueError(f'Trace must be an object with version {TRACE_VERSION}.')
    source = data.get('source')
    if (not isinstance(source, dict) or not isinstance(source.get('kind'), str)
            or source['kind'] not in {'video', 'synthetic', 'trace'}):
        raise ValueError('Trace source.kind must be video, synthetic, or trace.')
    if 'fps' in source and _number(source['fps'], 'source.fps') <= 0:
        raise ValueError('source.fps must be greater than zero.')
    frames = data.get('frames')
    if not isinstance(frames, list) or not frames:
        raise ValueError('Trace frames must be a nonempty array.')
    clean_frames = []
    previous = -1.0
    for index, frame in enumerate(frames):
        label = f'frames[{index}]'
        if not isinstance(frame, dict):
            raise ValueError(f'{label} must be an object.')
        timestamp = _number(frame.get('timestamp'), f'{label}.timestamp')
        if timestamp <= previous:
            raise ValueError('Frame timestamps must be strictly increasing.')
        previous = timestamp
        for field in ('inPlank', 'hasPose'):
            if type(frame.get(field)) is not bool:
                raise ValueError(f'{label}.{field} must be true or false.')
        quality = frame.get('quality')
        if not isinstance(quality, str) or quality not in QUALITIES:
            raise ValueError(f'{label}.quality must be valid, uncertain, or invalid.')
        reason = frame.get('reason')
        if reason is not None and (not isinstance(reason, str) or not reason.strip()):
            raise ValueError(f'{label}.reason must be a nonempty string, or null.')
        clean_frames.append({
            'timestamp': timestamp,
            'leftAngle': _angle(frame.get('leftAngle'), f'{label}.leftAngle'),
            'rightAngle': _angle(frame.get('rightAngle'), f'{label}.rightAngle'),
            'inPlank': frame['inPlank'], 'hasPose': frame['hasPose'],
            'quality': quality, 'reason': reason,
            'imageLandmarks': _landmarks(frame.get('imageLandmarks'), f'{label}.imageLandmarks'),
            'worldLandmarks': _landmarks(frame.get('worldLandmarks'), f'{label}.worldLandmarks'),
        })
    return {'version': TRACE_VERSION, 'source': source, 'frames': clean_frames}


def _reject_constant(value: str) -> None:
    raise ValueError(f'JSON contains {value}; use null for a missing angle.')


def read_json(path: Path) -> Any:
    # Keep file errors readable and reject special numbers that JSON cannot safely store.
    try:
        return json.loads(path.read_text(encoding='utf-8'), parse_constant=_reject_constant)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'Could not read JSON from {path.name}: {exc}') from exc


def load_trace(path: Path) -> dict[str, Any]:
    return validate_trace(read_json(path))


def _export_landmarks(points: Any) -> list[dict[str, float]] | None:
    # Save plain numbers so a recorded pose can be tested again without the video.
    if points is None:
        return None
    if hasattr(points, 'landmark'):
        points = points.landmark
    exported = []
    for point in points:
        result = {}
        for field in ('x', 'y', 'z', 'visibility', 'presence'):
            value = point.get(field) if isinstance(point, dict) else getattr(point, field, None)
            if value is not None:
                result[field] = float(value)
        exported.append(result)
    return exported


def trace_video(path: Path) -> tuple[dict[str, Any], float]:
    """Read a local file. Use the recorded frame rate to build its timeline."""
    if not path.is_file():
        raise ValueError(f'Video file does not exist: {path}')
    # Keep video dependencies optional for pure JSON replay.
    import cv2
    from .vision import PoseProcessor

    capture = cv2.VideoCapture(str(path.resolve()))
    processor = None
    started = time.perf_counter()
    try:
        if not capture.isOpened():
            raise ValueError(f'Could not open video: {path.name}')
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError('Video has no valid recorded FPS. Re-export it at a constant frame rate.')
        processor = PoseProcessor()
        frames = []
        while True:
            ok, image = capture.read()
            if not ok:
                break
            _, left, right, in_plank, has_pose = processor.process(image)
            assessment = processor.assessment
            frames.append({
                'timestamp': len(frames) / fps,
                'leftAngle': float(left) if math.isfinite(left) else None,
                'rightAngle': float(right) if math.isfinite(right) else None,
                'inPlank': bool(in_plank), 'hasPose': bool(has_pose),
                'quality': assessment.quality, 'reason': assessment.reason,
                'imageLandmarks': _export_landmarks(processor.last_landmarks),
                'worldLandmarks': _export_landmarks(processor.last_world_landmarks),
            })
        if not frames:
            raise ValueError(f'Video has no readable frames: {path.name}')
        trace = validate_trace({
            'version': TRACE_VERSION,
            'source': {'kind': 'video', 'file': path.name, 'fps': fps},
            'frames': frames,
        })
        return trace, time.perf_counter() - started
    finally:
        capture.release()
        if processor is not None:
            processor.close()


def validate_expected_times(values: Any) -> list[float]:
    # Manual labels mark when each real push up finishes in the recording.
    if not isinstance(values, list):
        raise ValueError('Expected completion timestamps must be a JSON array.')
    result = [_number(value, f'Expected timestamp {index}') for index, value in enumerate(values)]
    if any(right <= left for left, right in zip(result, result[1:])):
        raise ValueError('Expected completion timestamps must be strictly increasing.')
    return result


def match_completions(actual: Sequence[float], expected: Sequence[float], tolerance: float) -> dict[str, int]:
    """Pair each detected completion with at most one nearby manual label."""
    tolerance = _number(tolerance, 'Tolerance')
    observed = validate_expected_times(list(actual))
    labelled = validate_expected_times(list(expected))
    i = j = matched = 0
    while i < len(observed) and j < len(labelled):
        if observed[i] < labelled[j] - tolerance:
            i += 1
        elif labelled[j] < observed[i] - tolerance:
            j += 1
        else:
            matched += 1
            i += 1
            j += 1
    return {'matched': matched, 'missed': len(labelled) - matched, 'extra': len(observed) - matched}


def _measure_frame(frame: dict[str, Any]) -> dict[str, Any]:
    """Recheck saved body points when available, otherwise use saved measurements."""
    image_points, world_points = frame['imageLandmarks'], frame['worldLandmarks']
    if image_points is None and world_points is None:
        return frame
    # Convert saved points to the same attribute shape used by the live tracker.
    image = [SimpleNamespace(**({'visibility': 0.0} | point)) for point in image_points] if image_points is not None else None
    world = [SimpleNamespace(**point) for point in world_points] if world_points is not None else None
    assessment = assessPlank(image, world)
    left = float(calculateAngle(*[posePoint(world, index) for index in (11, 13, 15)]))
    right = float(calculateAngle(*[posePoint(world, index) for index in (12, 14, 16)]))
    return frame | {
        'leftAngle': left if math.isfinite(left) else None,
        'rightAngle': right if math.isfinite(right) else None,
        'inPlank': assessment.quality == 'valid', 'hasPose': image is not None,
        'quality': assessment.quality, 'reason': assessment.reason,
    }


def evaluate_trace(data: Any, *, expected_reps: int | None = None,
                   expected_times: list[float] | None = None,
                   tolerance: float = 0.5) -> dict[str, Any]:
    trace = validate_trace(data)
    frames = trace['frames']
    if expected_reps is not None and (type(expected_reps) is not int or expected_reps < 0):
        raise ValueError('Expected reps must be a nonnegative integer.')
    tolerance = _number(tolerance, 'Tolerance')
    if expected_times is not None:
        expected_times = validate_expected_times(expected_times)
        if expected_reps is not None and expected_reps != len(expected_times):
            raise ValueError('Expected rep total does not match the number of labelled timestamps.')
        expected_reps = len(expected_times)
        if any(value < frames[0]['timestamp'] or value > frames[-1]['timestamp'] for value in expected_times):
            raise ValueError('Expected completion timestamps must be within the trace timeline.')

    now = frames[0]['timestamp']
    tracker = PushUpTracker(clock=lambda: now)
    # Let the whole recording play even when it contains more reps than a set goal.
    tracker.goal = len(frames) + 1
    tracker.start()
    completions = []
    loss_seconds = 0.0
    loss_frames = 0
    invalid_seconds = 0.0
    landmark_frames = 0
    started = time.perf_counter()
    for index, frame in enumerate(frames):
        # The saved timeline controls hold times, independent of replay speed.
        if frame['imageLandmarks'] is not None or frame['worldLandmarks'] is not None:
            landmark_frames += 1
        frame = _measure_frame(frame)
        now = frame['timestamp']
        before = tracker.counter
        tracker.update(
            frame['leftAngle'] if frame['leftAngle'] is not None else math.nan,
            frame['rightAngle'] if frame['rightAngle'] is not None else math.nan,
            frame['inPlank'], frame['hasPose'],
            quality=frame['quality'], reason=frame['reason'],
        )
        if tracker.counter > before:
            completions.append(now)
        interval = frames[index + 1]['timestamp'] - now if index + 1 < len(frames) else 0.0
        # Measure each state until the following frame. The last frame has no interval.
        lost = tracker.tracking_quality == 'uncertain'
        if lost:
            loss_seconds += interval
            loss_frames += 1
        elif tracker.tracking_quality == 'invalid':
            invalid_seconds += interval
    processing_seconds = time.perf_counter() - started
    duration = frames[-1]['timestamp'] - frames[0]['timestamp']
    report = {
        'sourceKind': trace['source']['kind'],
        'frames': len(frames), 'durationSeconds': duration,
        'countedReps': tracker.counter, 'completionTimestamps': completions,
        'expectedReps': expected_reps,
        'countDifference': None if expected_reps is None else tracker.counter - expected_reps,
        'trackingLossSeconds': loss_seconds,
        'trackingLossRate': loss_seconds / duration if duration > 0 else 0.0,
        'trackingLossFrames': loss_frames,
        'invalidPostureSeconds': invalid_seconds,
        'processingFps': len(frames) / processing_seconds if processing_seconds > 0 else None,
        'processingMode': 'trace_landmark_geometry' if landmark_frames else 'trace_state_machine',
        'landmarkFrames': landmark_frames,
        'cachedMeasurementFrames': len(frames) - landmark_frames,
    }
    if expected_reps is not None:
        # A total alone reveals only the difference, since misses and extras can cancel out.
        difference = tracker.counter - expected_reps
        report['countComparison'] = 'overcount' if difference > 0 else 'undercount' if difference < 0 else 'equal'
    if expected_times is not None:
        report['completionMatches'] = match_completions(completions, expected_times, tolerance)
        report['matchToleranceSeconds'] = tolerance
    return report


def main(argv: Sequence[str] | None = None) -> int:
    # The command accepts local files and prints a report that can be saved as JSON.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='Local video file or exported .json trace')
    parser.add_argument('--expected-reps', type=int, help='Manually labelled total number of reps')
    parser.add_argument('--expected-times', type=Path, help='JSON array of labelled rep completion seconds')
    parser.add_argument('--tolerance', type=float, default=0.5, help='Completion match tolerance in seconds (default: 0.5)')
    parser.add_argument('--export', type=Path, help='Write a reusable JSON tracking trace')
    args = parser.parse_args(argv)
    try:
        if args.export is not None and args.export.resolve() == args.input.resolve():
            raise ValueError('Export path must differ from the input file.')
        video_seconds = None
        if args.input.suffix.lower() == '.json':
            trace = load_trace(args.input)
        else:
            trace, video_seconds = trace_video(args.input)
        expected_times = read_json(args.expected_times) if args.expected_times else None
        report = evaluate_trace(trace, expected_reps=args.expected_reps,
                                expected_times=expected_times, tolerance=args.tolerance)
        if video_seconds is not None:
            report['processingFps'] = len(trace['frames']) / video_seconds if video_seconds > 0 else None
            report['processingMode'] = 'video_pose_processing'
        if args.export is not None:
            args.export.write_text(json.dumps(trace, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, f'Replay error: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
