import cv2
import mediapipe as mp
import tkinter as tk
import numpy as np

# Set up MediaPipe
mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils

pose = mp_pose.Pose()

# Open webcam
camera = cv2.VideoCapture(0)
landmarkIds = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26]
# Shoulders are 11 and 12
# Elbows are 13 and 14
# Wrists are 15 and 16
# Hips are 23 and 24
# Kees are 25 and 26
connections = [(11, 12), (23, 24), (11, 13), (13, 15), (11, 23), 
               (23, 25), (12, 14), (14, 16), (12, 24), (24, 26)]
# Connect shoulders (11, 12)
# Connect hips (23, 24)
# Connect left shoulder to left elbow (11, 13)
# Connect left elbow to left wrist (13, 15)
# Connect left shoulder to left hip (11, 23)
# Connect left hip to left knee (23, 25)
# Connect right shoulder to right elbow (12, 14)
# Connect right elbow to right wrist (14, 16)
# Connect right shoulder to right hip (12, 24)
# Connect right hip to right knee (24, 26)

counter = 0
stage = None

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
    cosAngle  = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc))
    
    # Clip values to the valid range [-1.0, 1.0] to avoid floating point errors
    cosAngle = np.clip(cosAngle, -1.0, 1.0)
    
    # Calculate angle in radians and convert to degrees
    radians = np.arccos(cosAngle)
    return np.degrees(radians)

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

        # Get the coordinates of the shoulders, elbows, and wrists
        leftShoulder = [int(landmarks[11].x * frameWidth), int(landmarks[11].y * frameHeight)]
        rightShoulder = [int(landmarks[12].x * frameWidth), int(landmarks[12].y * frameHeight)]
        leftElbow = [int(landmarks[13].x * frameWidth), int(landmarks[13].y * frameHeight)]
        rightElbow = [int(landmarks[14].x * frameWidth), int(landmarks[14].y * frameHeight)]
        leftWrist = [int(landmarks[15].x * frameWidth), int(landmarks[15].y * frameHeight)]
        rightWrist = [int(landmarks[16].x * frameWidth), int(landmarks[16].y * frameHeight)]

        # Calculate angles at the elbows
        angleLeftElbow = calculateAngle(leftShoulder, leftElbow, leftWrist)
        angleRightElbow = calculateAngle(rightShoulder, rightElbow, rightWrist)

        # Visualize the angles on the frame
        cv2.putText(frame, str(int(angleLeftElbow)), 
                    tuple(leftElbow), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.putText(frame, str(int(angleRightElbow)), 
                    tuple(rightElbow), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv2.LINE_AA)

        # Push-up counting logic
        if angleLeftElbow > 160 and angleRightElbow > 160 and stage == None:
            stage = "up"
        if angleLeftElbow < 90 and angleRightElbow < 90 and stage == 'up':
            stage = "down"
        if angleLeftElbow > 160 and angleRightElbow > 160 and stage == 'down':
            stage = "up"
            counter += 1

        # Display the stage (up or down)
        cv2.putText(frame, f"Stage: {stage}", (50, 100), 
                    cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 255, 0), 3, cv2.LINE_AA)
        
    else:
        # If no landmarks are detected, display "Get in frame"
        cv2.putText(frame, "Get in frame", (50, 100), 
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