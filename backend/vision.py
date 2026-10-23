"""Find body points in an image and draw the tracking preview."""
from collections.abc import Sequence
from typing import Protocol, cast

import cv2
from cv2.typing import MatLike
from mediapipe.python.solutions.pose import Pose
import numpy as np
from numpy.typing import NDArray

from .tracker import MIN_VISIBILITY, PoseAssessment, assessPlank, calculateAngle, posePoint

# Only the torso and arms are needed. Hidden legs do not block tracking.
LANDMARK_IDS = (11, 12, 13, 14, 15, 16, 23, 24)
CONNECTIONS = ((11, 12), (23, 24), (11, 13), (13, 15),
               (11, 23), (12, 14), (14, 16), (12, 24))


class _Landmark(Protocol):
    """Describe one body point and how clearly the model can see it."""

    x: float
    y: float
    z: float
    visibility: float


class _LandmarkList(Protocol):
    """Describe the group of body points returned by the model."""

    landmark: Sequence[_Landmark]


class _PoseResult(Protocol):
    # MediaPipe creates these fields dynamically, but its return annotation
    # only says NamedTuple. Describe the fields we actually read here.
    pose_landmarks: _LandmarkList | None
    pose_world_landmarks: _LandmarkList | None


class PoseProcessor:
    """Keep the pose model open and process each new preview frame."""

    def __init__(self) -> None:
        # The default model already smooths body points between video frames.
        self.pose = Pose()
        self.assessment = PoseAssessment('uncertain', 'no_pose')
        self.last_landmarks: Sequence[_Landmark] | None = None
        self.last_world_landmarks: Sequence[_Landmark] | None = None

    def process(self, frame: MatLike) -> tuple[NDArray[np.uint8], float, float, bool, bool]:
        # Mirror the preview and change its colors into the format the model needs.
        frame = cast(NDArray[np.uint8], cv2.flip(frame, 1))
        result = cast(_PoseResult, self.pose.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        left_angle = right_angle = np.nan
        pose_landmarks = result.pose_landmarks
        world_landmarks = result.pose_world_landmarks
        landmarks = pose_landmarks.landmark if pose_landmarks is not None else None
        world = world_landmarks.landmark if world_landmarks is not None else None
        # Keep the latest model output available for local replay and debugging.
        self.last_landmarks = landmarks
        self.last_world_landmarks = world
        self.assessment = assessPlank(landmarks, world)
        if landmarks is not None:
            # Draw only clear points inside the image and the lines joining them.
            height, width = frame.shape[:2]
            points: dict[int, tuple[int, int]] = {}
            for index in LANDMARK_IDS:
                if index >= len(landmarks):
                    continue
                landmark = landmarks[index]
                if (np.isfinite([landmark.x, landmark.y, landmark.visibility]).all() and
                        landmark.visibility >= MIN_VISIBILITY and
                        0 <= landmark.x <= 1 and 0 <= landmark.y <= 1):
                    points[index] = (int(landmark.x * width), int(landmark.y * height))
                    cv2.circle(frame, points[index], 5, (126, 241, 193), cv2.FILLED)
            for start, end in CONNECTIONS:
                if start in points and end in points:
                    cv2.line(frame, points[start], points[end], (126, 241, 193), 2)
            # Spatial points measure each elbow bend even when the body faces the camera.
            left_angle = float(calculateAngle(*[posePoint(world, i) for i in (11, 13, 15)]))
            right_angle = float(calculateAngle(*[posePoint(world, i) for i in (12, 14, 16)]))
            if self.assessment.quality == 'valid' and not np.isfinite([left_angle, right_angle]).all():
                self.assessment = PoseAssessment('uncertain', 'invalid_landmarks')
            # Angle labels make the detected movement visible in the preview.
            for index, angle in ((13, left_angle), (14, right_angle)):
                if index in points and np.isfinite(angle):
                    cv2.putText(frame, str(int(angle)), points[index],
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        # Preserve the existing return values while exposing detailed feedback separately.
        in_plank = self.assessment.quality == 'valid'
        return frame, left_angle, right_angle, in_plank, pose_landmarks is not None

    def close(self) -> None:
        """Release the model when the camera or replay stops."""
        self.pose.close()
