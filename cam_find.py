import cv2

# Shows a picture from each camera with its number on it.
# Use the number of the overhead webcam as CAMERA_INDEX in collect_photos.py and detect.py.

for i in range(4):
    cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
    ok, frame = cap.read() if cap.isOpened() else (False, None)
    cap.release()
    if not ok:
        print(f"Camera {i}: not found")
        continue
    print(f"Camera {i}: found. Look at the window, press any key for the next one")
    cv2.putText(frame, f"CAMERA {i}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 255, 0), 3)
    cv2.imshow("Which camera is this?", frame)
    cv2.waitKey(0)
cv2.destroyAllWindows()
