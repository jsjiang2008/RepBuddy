"""Check body position and count movements using the time of each frame."""
from dataclasses import dataclass
import time
from typing import Literal

import numpy as np

# These limits allow small changes in the detected body position.
MIN_VISIBILITY = 0.5
MAX_BODY_TILT = 30
MAX_FRONT_ANGLE = 35
PLANK_GRACE_SECONDS = 0.5
ENDPOINT_HOLD_SECONDS = 0.12
MAX_FRAME_GAP_SECONDS = 0.25
ANGLE_HYSTERESIS = 4.0

TrackingQuality = Literal['valid', 'uncertain', 'invalid']


@dataclass(frozen=True)
class PoseAssessment:
    """Describe whether a pose is clear, unclear, or definitely out of position."""

    quality: TrackingQuality
    reason: str | None = None


def calculateAngle(a, b, c):
    """Measure the bend at the middle point and reject unusable points."""
    a, b, c = (np.asarray(point, dtype=float) for point in (a, b, c))
    if not np.isfinite([a, b, c]).all():
        return np.nan
    ba, bc = a - b, c - b
    magnitude = np.linalg.norm(ba) * np.linalg.norm(bc)
    if magnitude <= 1e-12:
        return np.nan
    return float(np.degrees(np.arccos(np.clip(np.dot(ba, bc) / magnitude, -1, 1))))


def posePoint(worldLandmarks, index):
    """Read one body point in space and return missing values when unavailable."""
    try:
        point = worldLandmarks[index]
        return np.asarray([point.x, point.y, point.z], dtype=float)
    except (IndexError, KeyError, TypeError, AttributeError, ValueError):
        return np.full(3, np.nan)


def assessPlank(landmarks, worldLandmarks) -> PoseAssessment:
    """Check the torso and arms even when knees and ankles are hidden.

    Uncertain measurements suspend counting. Clearly wrong posture invalidates
    a partial rep immediately. A small geometry margin avoids treating boundary
    noise as definite bad form. This cannot verify straight legs.
    """
    if landmarks is None:
        return PoseAssessment('uncertain', 'no_pose')
    if worldLandmarks is None:
        return PoseAssessment('uncertain', 'world_landmarks_missing')
    # All required joints must be clear and inside the camera image.
    groups = (
        ('shoulders', (11, 12)), ('elbows', (13, 14)),
        ('wrists', (15, 16)), ('hips', (23, 24)),
    )
    points = {}
    for name, indexes in groups:
        for index in indexes:
            try:
                point = landmarks[index]
                measurement = np.asarray([point.x, point.y, point.visibility], dtype=float)
            except (IndexError, KeyError, TypeError, AttributeError, ValueError):
                return PoseAssessment('uncertain', f'{name}_not_visible')
            if not np.isfinite(measurement).all():
                return PoseAssessment('uncertain', 'invalid_landmarks')
            if point.visibility < MIN_VISIBILITY or not (0 <= point.x <= 1 and 0 <= point.y <= 1):
                return PoseAssessment('uncertain', f'{name}_not_visible')
            points[index] = posePoint(worldLandmarks, index)
    if not np.isfinite(list(points.values())).all():
        return PoseAssessment('uncertain', 'invalid_landmarks')
    # Compare the shoulders and hips to estimate body direction and tilt.
    shoulders = (points[11] + points[12]) / 2
    hips = (points[23] + points[24]) / 2
    torso = hips - shoulders
    torso_length = np.linalg.norm(torso)
    shoulder_line = points[12] - points[11]
    if torso_length <= 1e-6 or np.linalg.norm(shoulder_line) <= 1e-6:
        return PoseAssessment('uncertain', 'invalid_landmarks')

    body_tilt = np.degrees(np.arctan2(abs(torso[1]), np.linalg.norm(torso[[0, 2]])))
    facing_angle = np.degrees(np.arctan2(abs(torso[0]), torso[2]))
    shoulder_angle = np.degrees(np.arctan2(abs(shoulder_line[2]), abs(shoulder_line[0])))
    wrist_depth = min((points[wrist][1] - points[shoulder][1]) / torso_length
                      for shoulder, wrist in ((11, 15), (12, 16)))
    # Obvious posture problems reset a rep. Borderline readings only pause it.
    if body_tilt > MAX_BODY_TILT + 8:
        return PoseAssessment('invalid', 'torso_too_upright')
    if facing_angle > MAX_FRONT_ANGLE + 8 or shoulder_angle > MAX_FRONT_ANGLE + 8:
        return PoseAssessment('invalid', 'face_camera')
    if wrist_depth < 0.08:
        return PoseAssessment('invalid', 'hands_not_below_shoulders')
    if (body_tilt > MAX_BODY_TILT or facing_angle > MAX_FRONT_ANGLE or
            shoulder_angle > MAX_FRONT_ANGLE or wrist_depth <= 0.15):
        return PoseAssessment('uncertain', 'borderline_posture')
    return PoseAssessment('valid')


def isInPlank(landmarks, worldLandmarks):
    """Keep the simple yes or no check available to older callers."""
    return assessPlank(landmarks, worldLandmarks).quality == 'valid'


def _finite_angle(value):
    """Keep angles within their possible range and replace bad values with None."""
    try:
        angle = float(value)
        return angle if np.isfinite(angle) and 0 <= angle <= 180 else None
    except (TypeError, ValueError):
        return None


class PushUpTracker:
    """Store one workout. The camera service allows only one change at a time."""

    def __init__(self, clock=time.monotonic):
        # A supplied clock lets tests replay movements without waiting.
        self.clock = clock
        self.goal = 10
        self._thresholds = None
        self.calibration_state = 'idle'
        self.calibration_progress = 0.0
        self.calibration_message = 'Optional: calibrate for your camera position.'
        self._calibration_top = None
        self._calibration_bottom = None
        self._calibration_samples = []
        self._calibration_since = None
        self.reset()

    @property
    def calibrating(self):
        """Report whether the user is still completing the calibration steps."""
        return self.calibration_state in ('hold_up', 'lower', 'return_up')

    def _clear_candidate(self):
        """Forget an endpoint that has not been held long enough yet."""
        self._candidate = None
        self._candidate_since = None
        self._candidate_frames = 0

    def _clear_rep(self):
        """Discard only the unfinished rep and its temporary tracking delay."""
        self.stage = None
        self.invalid_since = None
        self._clear_candidate()

    def reset(self):
        """Clear the workout while keeping the chosen goal and saved calibration."""
        self.cancel_calibration()
        self.counter = 0
        self._clear_rep()
        self._last_frame_at = None
        self.in_plank = False
        self.has_pose = False
        self.tracking_quality = 'uncertain'
        self.tracking_reason = 'no_pose'
        self.left_angle = self.right_angle = None
        self.running = False
        self.elapsed = 0.0
        self.started_at = None

    def set_goal(self, goal):
        """Allow supported goals only before a set begins."""
        if type(goal) is not int or goal not in (5, 10, 15, 20):
            raise ValueError('Choose a rep goal of 5, 10, 15 or 20.')
        if self.running or self.elapsed > 0 or self.counter > 0:
            raise ValueError('Reset the set before changing its goal.')
        self.goal = goal

    def start(self):
        """Begin timing and require a fresh starting plank after every pause."""
        if self.calibrating:
            raise ValueError('Finish or cancel calibration before starting a set.')
        if self.counter >= self.goal:
            self.reset()
        if not self.running:
            self._clear_rep()
            self._last_frame_at = None
            self.started_at = self.clock()
            self.running = True

    def pause(self):
        """Save active time and discard any unfinished movement."""
        if self.running:
            self.elapsed += max(0.0, self.clock() - self.started_at)
        self.started_at = None
        self.running = False
        self._clear_rep()
        self._last_frame_at = None

    def begin_calibration(self):
        """Start learning the top and bottom angles without counting a workout."""
        if self.running:
            raise ValueError('Pause your set before calibrating.')
        self._clear_rep()
        self._last_frame_at = None
        self._calibration_top = self._calibration_bottom = None
        self._clear_calibration_hold()
        self.calibration_state = 'hold_up'
        self.calibration_progress = 0.0
        self.calibration_message = 'Hold a front-facing plank with both arms straight.'

    def cancel_calibration(self):
        """Leave calibration and keep any previously saved camera settings."""
        self._clear_calibration_hold()
        self._calibration_top = self._calibration_bottom = None
        self.calibration_state = 'ready' if self._thresholds is not None else 'idle'
        self.calibration_progress = 1.0 if self._thresholds is not None else 0.0
        self.calibration_message = ('Calibration saved for this camera position.' if self._thresholds is not None
                                    else 'Optional: calibrate for your camera position.')

    def clear_calibration(self):
        """Restore the default angle limits and discard the current movement."""
        self._thresholds = None
        self.cancel_calibration()
        self._clear_rep()

    def _clear_calibration_hold(self):
        """Forget samples from a position that stopped being steady."""
        self._calibration_since = None
        self._calibration_samples = []

    def _hold_calibration(self, angles, now, duration):
        # Reject moving endpoints instead of averaging a partial movement.
        if self._calibration_samples:
            candidate = np.asarray(self._calibration_samples + [angles])
            if np.any(np.ptp(candidate, axis=0) > 8):
                self._clear_calibration_hold()
        if self._calibration_since is None:
            self._calibration_since = now
        self._calibration_samples.append(angles)
        fraction = min(1.0, max(0.0, (now - self._calibration_since) / duration))
        if fraction >= 1.0 and len(self._calibration_samples) >= 3:
            return tuple(float(value) for value in np.median(self._calibration_samples, axis=0)), fraction
        return None, fraction

    def _update_calibration(self, angles, now):
        """Guide a steady top position, a full lowering, and a return to the top."""
        state = self.calibration_state
        if state == 'hold_up':
            if min(angles) < 150:
                self._clear_calibration_hold()
                self.calibration_progress = 0.0
                self.calibration_message = 'Straighten both arms, then hold still briefly.'
                return
            top, progress = self._hold_calibration(angles, now, 0.6)
            self.calibration_progress = progress / 3
            self.calibration_message = 'Hold your starting plank steady.'
            if top is not None:
                self._calibration_top = top
                self._clear_calibration_hold()
                self.calibration_state = 'lower'
                self.calibration_message = 'Lower into a full push-up and hold briefly.'
        elif state == 'lower':
            top = self._calibration_top
            if top is None:
                return
            if max(angles) > 100 or any(high - low < 55 for high, low in zip(top, angles)):
                self._clear_calibration_hold()
                self.calibration_progress = 1 / 3
                self.calibration_message = 'Lower further with both arms; shallow movements cannot calibrate.'
                return
            bottom, progress = self._hold_calibration(angles, now, 0.3)
            self.calibration_progress = (1 + progress) / 3
            self.calibration_message = 'Hold the bottom position steady.'
            if bottom is not None:
                self._calibration_bottom = bottom
                self._clear_calibration_hold()
                self.calibration_state = 'return_up'
                self.calibration_message = 'Return to your starting plank and straighten both arms.'
        elif state == 'return_up':
            top, bottom = self._calibration_top, self._calibration_bottom
            if top is None or bottom is None:
                return
            if any(angle < max(150, high - 8) for angle, high in zip(angles, top)):
                self._clear_calibration_hold()
                self.calibration_progress = 2 / 3
                return
            returned, progress = self._hold_calibration(angles, now, 0.3)
            self.calibration_progress = (2 + progress) / 3
            if returned is not None:
                # Limit the learned angles so shallow movements cannot become full reps.
                upper = tuple(max(150.0, min(165.0, min(a, b) - 8)) for a, b in zip(top, returned))
                lower = tuple(max(70.0, min(95.0, value + 8)) for value in bottom)
                self._thresholds = (upper, lower)
                self.cancel_calibration()

    def update(self, left_angle, right_angle, in_plank, has_pose, *, quality=None, reason=None):
        """Use one observed pose to update feedback, calibration, and rep progress."""
        now = self.clock()
        # Missing angles cannot advance a rep even if the torso looks correct.
        self.has_pose = bool(has_pose)
        self.left_angle, self.right_angle = _finite_angle(left_angle), _finite_angle(right_angle)
        quality = quality if quality in ('valid', 'uncertain', 'invalid') else ('valid' if in_plank else 'uncertain')
        if not self.has_pose:
            quality, reason = 'uncertain', 'no_pose'
        elif self.left_angle is None or self.right_angle is None:
            # Preserve a definite posture failure if geometry already established it.
            if quality != 'invalid':
                quality, reason = 'uncertain', reason or 'invalid_landmarks'
        elif quality == 'valid' and not in_plank:
            quality, reason = 'uncertain', reason or 'borderline_posture'
        self.tracking_quality = quality
        self.tracking_reason = reason
        self.in_plank = quality == 'valid' and bool(in_plank)

        # A repeated timestamp adds no evidence. Long gaps cannot finish a hold.
        previous = self._last_frame_at
        fresh = previous is None or now > previous
        gap = 0 if previous is None else now - previous
        if gap > MAX_FRAME_GAP_SECONDS or gap < 0:
            self._clear_candidate()
            self._clear_calibration_hold()
        if gap >= PLANK_GRACE_SECONDS or gap < 0:
            self._clear_rep()
        if fresh or gap < 0:
            self._last_frame_at = now

        if self.calibrating:
            # Learning needs clear tracking and never adds reps or workout time.
            if quality != 'valid':
                self._clear_calibration_hold()
                self.calibration_progress = {'hold_up': 0.0, 'lower': 1 / 3, 'return_up': 2 / 3}[self.calibration_state]
                self.calibration_message = 'Adjust your position until tracking is clear, then hold still.'
            elif fresh:
                self._update_calibration((self.left_angle, self.right_angle), now)
            return
        if not self.running:
            return

        # Brief uncertainty keeps the last stage, but known bad posture clears it.
        if self.invalid_since is not None and now - self.invalid_since >= PLANK_GRACE_SECONDS:
            self._clear_rep()
        if quality == 'invalid':
            self._clear_rep()
            return
        if quality != 'valid':
            self._clear_candidate()
            if self.stage is not None and self.invalid_since is None:
                self.invalid_since = now
            return
        self.invalid_since = None
        if not fresh:
            return

        # Both arms must reach the next endpoint and remain there briefly.
        upper, lower = self._thresholds or ((160.0, 160.0), (90.0, 90.0))
        angles = (self.left_angle, self.right_angle)
        target = 'down' if self.stage == 'up' else 'up'
        limits = lower if target == 'down' else upper
        enters = (all(a <= b for a, b in zip(angles, limits)) if target == 'down'
                  else all(a >= b for a, b in zip(angles, limits)))
        remains = (all(a <= b + ANGLE_HYSTERESIS for a, b in zip(angles, limits)) if target == 'down'
                   else all(a >= b - ANGLE_HYSTERESIS for a, b in zip(angles, limits)))
        self.tracking_reason = 'lower_body' if target == 'down' else 'extend_arms'
        if self._candidate != target:
            self._clear_candidate()
            if enters:
                self._candidate = target
                self._candidate_since = now
                self._candidate_frames = 1
        elif not remains:
            self._clear_candidate()
        else:
            self._candidate_frames += 1
            if now - self._candidate_since >= ENDPOINT_HOLD_SECONDS and self._candidate_frames >= 2:
                completed = self.stage == 'down' and target == 'up'
                self.stage = target
                self._clear_candidate()
                self.counter += int(completed)
                self.tracking_reason = 'lower_body' if target == 'up' else 'extend_arms'
                if self.counter >= self.goal:
                    self.pause()

    def snapshot(self):
        """Build the current status sent to the interface without changing the workout."""
        elapsed = self.elapsed
        if self.running:
            elapsed += max(0.0, self.clock() - self.started_at)
        return {
            'reps': self.counter, 'goal': self.goal, 'stage': self.stage,
            'inPlank': self.in_plank, 'hasPose': self.has_pose,
            'running': self.running, 'completed': self.counter >= self.goal,
            'inGracePeriod': self.running and self.invalid_since is not None,
            'elapsedSeconds': round(elapsed, 2),
            'trackingQuality': self.tracking_quality, 'trackingReason': self.tracking_reason,
            'leftAngle': self.left_angle, 'rightAngle': self.right_angle,
            'calibrationState': self.calibration_state,
            'calibrationProgress': self.calibration_progress,
            'calibrationMessage': self.calibration_message,
        }
