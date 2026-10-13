"""Camera-frame analysis, shared by the API and standalone window."""
from collections.abc import Sequence
from typing import Protocol, cast

import cv2
from cv2.typing import MatLike
from mediapipe.python.solutions.pose import Pose
import numpy as np
from numpy.typing import NDArray

from .tracker import MIN_VISIBILITY, calculateAngle, isInPlank, posePoint

LANDMARK_IDS = (11, 12, 13, 14, 15, 16, 23, 24)
CONNECTIONS = ((11, 12), (23, 24), (11, 13), (13, 15),
               (11, 23), (12, 14), (14, 16), (12, 24))


class _Landmark(Protocol):
    x: float
    y: float
    z: float
    visibility: float


class _LandmarkList(Protocol):
    landmark: Sequence[_Landmark]


class _PoseResult(Protocol):
    # MediaPipe creates these fields dynamically, but its return annotation
    # only says NamedTuple. Describe the fields we actually read here.
    pose_landmarks: _LandmarkList | None
    pose_world_landmarks: _LandmarkList | None


class PoseProcessor:
    def __init__(self) -> None:
        self.pose = Pose()

    def process(self, frame: MatLike) -> tuple[NDArray[np.uint8], float, float, bool, bool]:
        # OpenCV preserves this frame's uint8 dtype when flipping it.
        frame = cast(NDArray[np.uint8], cv2.flip(frame, 1))
        result = cast(_PoseResult, self.pose.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        left_angle = right_angle = np.nan
        in_plank = False
        pose_landmarks = result.pose_landmarks
        world_landmarks = result.pose_world_landmarks
        if pose_landmarks is not None:
            landmarks = pose_landmarks.landmark
            world = world_landmarks.landmark if world_landmarks is not None else None
            height, width = frame.shape[:2]
            points: dict[int, tuple[int, int]] = {}
            for index in LANDMARK_IDS:
                landmark = landmarks[index]
                if (landmark.visibility >= MIN_VISIBILITY and
                        np.isfinite([landmark.x, landmark.y]).all()):
                    points[index] = (int(landmark.x * width), int(landmark.y * height))
                    cv2.circle(frame, points[index], 5, (126, 241, 193), cv2.FILLED)
            for start, end in CONNECTIONS:
                if start in points and end in points:
                    cv2.line(frame, points[start], points[end], (126, 241, 193), 2)
            left_angle = float(calculateAngle(*[posePoint(world, i) for i in (11, 13, 15)]))
            right_angle = float(calculateAngle(*[posePoint(world, i) for i in (12, 14, 16)]))
            for index, angle in ((13, left_angle), (14, right_angle)):
                if index in points and np.isfinite(angle):
                    cv2.putText(frame, str(int(angle)), points[index],
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            in_plank = bool(isInPlank(landmarks, world))
        return frame, left_angle, right_angle, in_plank, pose_landmarks is not None

    def close(self) -> None:
        self.pose.close()
