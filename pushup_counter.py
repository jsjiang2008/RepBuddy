"""
Pushup Counter using Webcam Pose Tracking
-------------------------------------------
Uses MediaPipe Pose to track your elbow angle and count pushup reps
in real time from your webcam feed.

SETUP:
    pip install opencv-python mediapipe

RUN:
    python pushup_counter.py

CONTROLS:
    q - quit
    r - reset rep counter

TIPS FOR BEST TRACKING:
    - Position yourself so your SIDE faces the camera (not straight-on).
    - Make sure your whole body (shoulder to wrist, roughly hip too) is in frame.
    - Good, even lighting helps a lot.
"""

import cv2
import mediapipe as mp
import numpy as np

mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils


def calculate_angle(a, b, c):
    """Calculate the angle (in degrees) at point b, formed by points a-b-c."""
    a = np.array(a)
    b = np.array(b)
    c = np.array(c)

    radians = np.arctan2(c[1] - b[1], c[0] - b[0]) - np.arctan2(a[1] - b[1], a[0] - b[0])
    angle = np.abs(radians * 180.0 / np.pi)

    if angle > 180.0:
        angle = 360 - angle

    return angle


def get_landmark_xy(landmarks, landmark_enum, width, height):
    lm = landmarks[landmark_enum.value]
    return [lm.x * width, lm.y * height]


def main():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Error: Could not open webcam. Check that it's connected and not in use by another app.")
        return

    # Rep counting state
    counter = 0
    stage = None  # "up" or "down"

    # Angle thresholds (tune these if counting feels off)
    DOWN_ANGLE_THRESHOLD = 90   # elbow bent -> considered "down" position
    UP_ANGLE_THRESHOLD = 160    # elbow extended -> considered "up" position

    with mp_pose.Pose(min_detection_confidence=0.6, min_tracking_confidence=0.6) as pose:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                print("Failed to grab frame from camera.")
                break

            # Flip for a mirror-like view, convert color for MediaPipe
            frame = cv2.flip(frame, 1)
            height, width, _ = frame.shape
            image_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image_rgb.flags.writeable = False
            results = pose.process(image_rgb)
            image_rgb.flags.writeable = True

            angle_display = None

            try:
                landmarks = results.pose_landmarks.landmark

                # Try right side first, fall back to left if right isn't visible enough
                def visibility(landmark_enum):
                    return landmarks[landmark_enum.value].visibility

                use_right = visibility(mp_pose.PoseLandmark.RIGHT_ELBOW) >= visibility(mp_pose.PoseLandmark.LEFT_ELBOW)

                if use_right:
                    shoulder = get_landmark_xy(landmarks, mp_pose.PoseLandmark.RIGHT_SHOULDER, width, height)
                    elbow = get_landmark_xy(landmarks, mp_pose.PoseLandmark.RIGHT_ELBOW, width, height)
                    wrist = get_landmark_xy(landmarks, mp_pose.PoseLandmark.RIGHT_WRIST, width, height)
                else:
                    shoulder = get_landmark_xy(landmarks, mp_pose.PoseLandmark.LEFT_SHOULDER, width, height)
                    elbow = get_landmark_xy(landmarks, mp_pose.PoseLandmark.LEFT_ELBOW, width, height)
                    wrist = get_landmark_xy(landmarks, mp_pose.PoseLandmark.LEFT_WRIST, width, height)

                angle = calculate_angle(shoulder, elbow, wrist)
                angle_display = angle

                # Rep counting logic (state machine)
                if angle < DOWN_ANGLE_THRESHOLD:
                    stage = "down"
                if angle > UP_ANGLE_THRESHOLD and stage == "down":
                    stage = "up"
                    counter += 1

                # Draw the elbow angle near the elbow point
                cv2.putText(frame, f"{int(angle)} deg", tuple(np.array(elbow).astype(int)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)

            except AttributeError:
                # No person detected in frame this cycle
                pass

            # Draw pose landmarks/skeleton
            if results.pose_landmarks:
                mp_drawing.draw_landmarks(
                    frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS,
                    mp_drawing.DrawingSpec(color=(0, 200, 0), thickness=2, circle_radius=2),
                    mp_drawing.DrawingSpec(color=(255, 255, 255), thickness=2)
                )

            # --- HUD overlay ---
            cv2.rectangle(frame, (0, 0), (260, 90), (20, 20, 20), -1)
            cv2.putText(frame, "PUSHUPS", (15, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1, cv2.LINE_AA)
            cv2.putText(frame, str(counter), (15, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (0, 255, 0), 3, cv2.LINE_AA)
            stage_text = stage.upper() if stage else "-"
            cv2.putText(frame, f"stage: {stage_text}", (120, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)

            cv2.putText(frame, "q: quit   r: reset", (15, height - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1, cv2.LINE_AA)

            cv2.imshow("Pushup Counter", frame)

            key = cv2.waitKey(10) & 0xFF
            if key == ord('q'):
                break
            elif key == ord('r'):
                counter = 0
                stage = None

    cap.release()
    cv2.destroyAllWindows()
    print(f"Session ended. Total pushups counted: {counter}")


if __name__ == "__main__":
    main()
