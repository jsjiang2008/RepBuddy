"""Match camera names and capture indices without opening devices to list them."""
import sys


def camera_backend():
    import cv2

    if sys.platform == 'win32':
        return cv2.CAP_DSHOW
    if sys.platform == 'darwin':
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_V4L2


def list_video_devices():
    # This enumerates OS device metadata; it does not acquire a camera stream.
    from cv2_enumerate_cameras import enumerate_cameras

    return [{'index': camera.index, 'name': camera.name}
            for camera in enumerate_cameras(camera_backend())]


def open_video_capture(index):
    import cv2

    # Use the same backend as enumeration so names map to the correct index.
    return cv2.VideoCapture(index, camera_backend())
