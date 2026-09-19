import cv2
import mediapipe as mp
import tkinter as tk

# Set up MediaPipe
mp_pose = mp.solutions.pose
mp_drawing = mp.solutions.drawing_utils

pose = mp_pose.Pose()

# Open webcam
camera = cv2.VideoCapture(0)
landmarks = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26]
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

def calculateAngle(shoulder, elbow, wrist) :
    angle = 0
    return angle

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


while True:

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

    # Draw body landmarks and lines
    if results.pose_landmarks:
        h, w, c = frame.shape
        drawnLandmarks = {}
        
        # Loop through only the specific IDs you want
        for lmId in landmarks:
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
        

    # Original camera dimensions
    frame_height, frame_width = frame.shape[:2]

    # Calculate scale while preserving aspect ratio
    scale = min(
        screen_width / frame_width,
        screen_height / frame_height
    )

    new_width = int(frame_width * scale)
    new_height = int(frame_height * scale)

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

    cv2.imshow("Push-Up Tracker", fullscreen)
    
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

camera.release()
cv2.destroyAllWindows()