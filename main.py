import cv2
import mediapipe as mp
import tkinter as tk
import numpy as np
import time

# Set up MediaPipe
mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils

pose = mp_pose.Pose()

# Open webcam
camera = cv2.VideoCapture(0)
landmarkIds = [11, 12, 13, 14, 15, 16, 23, 24]
# Shoulders are 11 and 12
# Elbows are 13 and 14
# Wrists are 15 and 16
# Hips are 23 and 24
connections = [(11, 12), (23, 24), (11, 13), (13, 15), (11, 23), 
               (12, 14), (14, 16), (12, 24)]
# Connect shoulders (11, 12)
# Connect hips (23, 24)
# Connect left shoulder to left elbow (11, 13)
# Connect left elbow to left wrist (13, 15)
# Connect left shoulder to left hip (11, 23)
# Connect right shoulder to right elbow (12, 14)
# Connect right elbow to right wrist (14, 16)
# Connect right shoulder to right hip (12, 24)

counter = 0
stage = None
invalidSince = None

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

# Set up window
cv2.namedWindow("Push-Up Tracker", cv2.WINDOW_NORMAL)
cv2.setWindowProperty(
    "Push-Up Tracker",
    cv2.WND_PROP_FULLSCREEN,
    cv2.WINDOW_FULLSCREEN
)

# Initialize a tkinter root window
root = tk.Tk()

# Withdraw the window so it doesn't appear on the screen
root.withdraw()

# Get screen width and height in pixels
screen_width = root.winfo_screenwidth()
screen_height = root.winfo_screenheight()


while camera.isOpened():

    success, frame = camera.read()
    frame = cv2.flip(frame, 1)


    if not success:
        print("Could not read camera")
        break

    # OpenCV uses BGR
    # MediaPipe expects RGB
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    # Detect body
    results = pose.process(rgb_frame)

    # Original camera dimensions
    frameHeight, frameWidth = frame.shape[:2]
    inPlank = False
    angleLeftElbow = angleRightElbow = np.nan

    # Draw body landmarks and lines
    if results.pose_landmarks:
        h, w, c = frame.shape
        drawnLandmarks = {}
        
        # Loop through only the specific IDs you want
        for lmId in landmarkIds:
            # Get the landmark by its ID
            landmark = results.pose_landmarks.landmark[lmId]

            if landmark.visibility > 0.5:
                # Convert normalized coordinates (0.0 to 1.0) to pixel coordinates
                cx, cy = int(landmark.x * w), int(landmark.y * h)

                # Add to drawn landmarks
                drawnLandmarks[lmId] = (cx, cy)
                
                # Draw the specific landmark using OpenCV
                cv2.circle(frame, (cx, cy), 8, (0, 255, 0), cv2.FILLED)   

        # Drawn lines
        for start, end in connections:
            if start in drawnLandmarks and end in drawnLandmarks:
                cv2.line(frame, drawnLandmarks[start], drawnLandmarks[end], (255, 0, 0), 3)

        # Get the landmarks for further processing if needed
        landmarks = results.pose_landmarks.landmark
        worldLandmarks = (results.pose_world_landmarks.landmark
                          if results.pose_world_landmarks else None)

        # Image coordinates position the elbow-angle labels on the frame.
        leftElbow = [int(landmarks[13].x * frameWidth), int(landmarks[13].y * frameHeight)]
        rightElbow = [int(landmarks[14].x * frameWidth), int(landmarks[14].y * frameHeight)]

        # Depth matters when facing the camera: projected 2D elbow angles
        # can look straight even when the arms are bent toward the camera.
        angleLeftElbow = calculateAngle(*[
            posePoint(worldLandmarks, index)
            for index in [11, 13, 15]
        ])
        angleRightElbow = calculateAngle(*[
            posePoint(worldLandmarks, index)
            for index in [12, 14, 16]
        ])

        # Visualize the angles on the frame
        cv2.putText(frame, str(int(angleLeftElbow)) if np.isfinite(angleLeftElbow) else "?",
                    tuple(leftElbow), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, str(int(angleRightElbow)) if np.isfinite(angleRightElbow) else "?",
                    tuple(rightElbow), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv2.LINE_AA)

        inPlank = isInPlank(landmarks, worldLandmarks)

    # Apply the same grace period to bad posture, missing joints and a
    # completely missing pose. Monotonic time makes it independent of FPS.
    stage, completedRep, invalidSince = updatePushUpStage(
        stage, angleLeftElbow, angleRightElbow, inPlank,
        invalidSince, time.monotonic())
    counter += completedRep

    cv2.putText(frame, f"Stage: {stage}", (50, 100),
                cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 255, 0), 3, cv2.LINE_AA)
    # Suppress posture warnings while an active rep is within its grace period.
    if stage is None:
        if results.pose_landmarks:
            cv2.putText(frame, "Face camera in plank - show arms and hips", (50, 150),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
        else:
            cv2.putText(frame, "Get in frame", (50, 150),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2, cv2.LINE_AA)
        
        

    # Calculate scale while preserving aspect ratio
    scale = min(
        screen_width / frameWidth,
        screen_height / frameHeight
    )

    new_width = int(frameWidth * scale)
    new_height = int(frameHeight * scale)

    # Resize without stretching
    resized_frame = cv2.resize(
        frame,
        (new_width, new_height)
    )

    # Create black fullscreen background
    fullscreen = cv2.copyMakeBorder(
        resized_frame,
        (screen_height - new_height) // 2,
        (screen_height - new_height + 1) // 2,
        (screen_width - new_width) // 2,
        (screen_width - new_width + 1) // 2,
        cv2.BORDER_CONSTANT,
        value=(0, 0, 0)
    )

    # Display the push-up counter
    cv2.putText(fullscreen, f'Push-Ups: {counter}', (50, 100), 
                cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 255, 0), 3, cv2.LINE_AA)


    # Display the frame
    cv2.imshow("Push-Up Tracker", fullscreen)
    
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

camera.release()
cv2.destroyAllWindows()
