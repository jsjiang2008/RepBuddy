"""Pose geometry and rep state; importing this module never opens a camera."""
import time
import numpy as np

MIN_VISIBILITY = 0.5
MAX_BODY_TILT = 30
MAX_FRONT_ANGLE = 35
PLANK_GRACE_SECONDS = 0.5

# Calculate angle between 3 points a, b, and c
def calculateAngle(a, b, c) :
    # Convert to numpy array objects
    a = np.array(a)
    b = np.array(b)
    c = np.array(c)

    # Create two vectors
    ba = a - b
    bc = c - b
    
    # Calculate cosine of the angle using the dot product formula
    magnitude = np.linalg.norm(ba) * np.linalg.norm(bc)
    if magnitude == 0:
        return np.nan
    cosAngle = np.dot(ba, bc) / magnitude
    
    # Clip values to the valid range [-1.0, 1.0] to avoid floating point errors
    cosAngle = np.clip(cosAngle, -1.0, 1.0)
    
    # Calculate angle in radians and convert to degrees
    radians = np.arccos(cosAngle)
    return np.degrees(radians)


def posePoint(worldLandmarks, index):
    if worldLandmarks is None:
        return np.full(3, np.nan)
    point = worldLandmarks[index]
    return np.array([point.x, point.y, point.z])


def isInPlank(landmarks, worldLandmarks):
    # Front-facing torso check: knees and ankles can be completely hidden.
    # This estimates plank posture but cannot verify straight legs.
    if worldLandmarks is None:
        return False
    required = [11, 12, 13, 14, 15, 16, 23, 24]
    if any(not (landmarks[index].visibility >= MIN_VISIBILITY and
                0 <= landmarks[index].x <= 1 and
                0 <= landmarks[index].y <= 1) for index in required):
        return False
    points = {index: posePoint(worldLandmarks, index) for index in required}
    if not np.isfinite(list(points.values())).all():
        return False

    shoulders = (points[11] + points[12]) / 2
    hips = (points[23] + points[24]) / 2
    torso = hips - shoulders
    torsoLength = np.linalg.norm(torso)
    shoulderLine = points[12] - points[11]
    if torsoLength == 0 or np.linalg.norm(shoulderLine) == 0:
        return False

    # With a level camera, a plank torso is roughly horizontal and extends
    # away from the lens (+z). Sideways and upright poses must not count.
    bodyTilt = np.degrees(np.arctan2(abs(torso[1]),
                                    np.linalg.norm(torso[[0, 2]])))
    facingAngle = np.degrees(np.arctan2(abs(torso[0]), torso[2]))
    shoulderAngle = np.degrees(np.arctan2(abs(shoulderLine[2]),
                                         abs(shoulderLine[0])))
    handsBelowShoulders = all(
        points[wrist][1] - points[shoulder][1] > 0.15 * torsoLength
        for shoulder, wrist in [(11, 15), (12, 16)]
    )
    return (bodyTilt <= MAX_BODY_TILT and facingAngle <= MAX_FRONT_ANGLE and
            shoulderAngle <= MAX_FRONT_ANGLE and handsBelowShoulders)


def updatePushUpStage(stage, leftAngle, rightAngle, inPlank, invalidSince, now):
    # Expire before processing recovery so a long gap cannot finish an old rep.
    if invalidSince is not None and now - invalidSince >= PLANK_GRACE_SECONDS:
        stage = None

    if not inPlank or not np.isfinite([leftAngle, rightAngle]).all():
        if stage is None:
            return None, 0, None
        if invalidSince is None:
            invalidSince = now
        # Preserve progress during a brief dropout, but never count or
        # change stages using an invalid frame.
        return stage, 0, invalidSince

    if leftAngle > 160 and rightAngle > 160:
        return "up", int(stage == "down"), None
    if leftAngle < 90 and rightAngle < 90 and stage == "up":
        return "down", 0, None
    return stage, 0, None


class PushUpTracker:
    """Single-session state. The camera service serializes access with a lock."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.goal = 10
        self.reset()

    def reset(self):
        self.counter = 0
        self.stage = None
        self.invalid_since = None
        self.in_plank = False
        self.has_pose = False
        self.running = False
        self.elapsed = 0.0
        self.started_at = None

    def set_goal(self, goal):
        if type(goal) is not int or goal not in (5, 10, 15, 20):
            raise ValueError('Choose a rep goal of 5, 10, 15 or 20.')
        if self.running or self.elapsed > 0 or self.counter > 0:
            raise ValueError('Reset the set before changing its goal.')
        self.goal = goal

    def start(self):
        if self.counter >= self.goal:
            self.reset()
        if not self.running:
            self.stage = None
            self.invalid_since = None
            self.started_at = self.clock()
            self.running = True

    def pause(self):
        if self.running:
            self.elapsed += self.clock() - self.started_at
        self.started_at = None
        self.running = False
        # A partial rep must not cross a manual pause or stop.
        self.stage = None
        self.invalid_since = None

    def update(self, left_angle, right_angle, in_plank, has_pose):
        self.in_plank = bool(in_plank)
        self.has_pose = bool(has_pose)
        if self.running:
            self.stage, completed, self.invalid_since = updatePushUpStage(
                self.stage, left_angle, right_angle, self.in_plank,
                self.invalid_since, self.clock())
            self.counter += completed
            if self.counter >= self.goal:
                self.pause()

    def snapshot(self):
        elapsed = self.elapsed
        if self.running:
            elapsed += self.clock() - self.started_at
        return {
            'reps': self.counter, 'goal': self.goal, 'stage': self.stage,
            'inPlank': self.in_plank, 'hasPose': self.has_pose,
            'running': self.running, 'completed': self.counter >= self.goal,
            'inGracePeriod': self.running and self.invalid_since is not None,
            'elapsedSeconds': round(elapsed, 2),
        }

