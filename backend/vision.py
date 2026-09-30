"""Camera-frame analysis, shared by the API and standalone window."""
import cv2
import mediapipe as mp
import numpy as np

from .tracker import MIN_VISIBILITY, calculateAngle, isInPlank, posePoint

LANDMARK_IDS = (11, 12, 13, 14, 15, 16, 23, 24)
CONNECTIONS = ((11, 12), (23, 24), (11, 13), (13, 15),
               (11, 23), (12, 14), (14, 16), (12, 24))


class PoseProcessor:
    def __init__(self):
        self.pose = mp.solutions.pose.Pose()

    def process(self, frame):
        frame = cv2.flip(frame, 1)
        result = self.pose.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        left_angle = right_angle = np.nan
        in_plank = False
        if result.pose_landmarks:
            landmarks = result.pose_landmarks.landmark
            world = (result.pose_world_landmarks.landmark
                     if result.pose_world_landmarks else None)
            height, width = frame.shape[:2]
            points = {}
            for index in LANDMARK_IDS:
                landmark = landmarks[index]
                if (landmark.visibility >= MIN_VISIBILITY and
                        np.isfinite([landmark.x, landmark.y]).all()):
                    points[index] = (int(landmark.x * width), int(landmark.y * height))
                    cv2.circle(frame, points[index], 5, (126, 241, 193), cv2.FILLED)
            for start, end in CONNECTIONS:
                if start in points and end in points:
                    cv2.line(frame, points[start], points[end], (126, 241, 193), 2)
            left_angle = calculateAngle(*[posePoint(world, i) for i in (11, 13, 15)])
            right_angle = calculateAngle(*[posePoint(world, i) for i in (12, 14, 16)])
            for index, angle in ((13, left_angle), (14, right_angle)):
                if index in points and np.isfinite(angle):
                    cv2.putText(frame, str(int(angle)), points[index],
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            in_plank = isInPlank(landmarks, world)
        return frame, left_angle, right_angle, in_plank, bool(result.pose_landmarks)

    def close(self):
        self.pose.close()
