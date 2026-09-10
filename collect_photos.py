import cv2
import os
import time

PRODUCT_NAME = "webcam_box"
SAVE_DIR     = f"dataset/{PRODUCT_NAME}"
CAMERA_INDEX = 1
TOTAL_PHOTOS = 100
DELAY        = 0.3

os.makedirs(SAVE_DIR, exist_ok=True)

cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

if not cap.isOpened():
    print(f"ERROR: Cannot open camera {CAMERA_INDEX}")
    exit()

print(f"Camera {CAMERA_INDEX} opened successfully")
print(f"Collecting {TOTAL_PHOTOS} photos for '{PRODUCT_NAME}'")
print("Press SPACE to start. Move box slightly between shots. Press Q to quit.")

count = 0
started = False

while True:
    ret, frame = cap.read()
    if not ret:
        print("Cannot read frame")
        continue

    display = frame.copy()

    if started:
        label = f"Photos: {count}/{TOTAL_PHOTOS}"
        color = (0, 255, 0)
    else:
        label = "Press SPACE to start"
        color = (0, 165, 255)

    cv2.putText(display, label, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

    cv2.imshow("Photo Collection", display)
    key = cv2.waitKey(1) & 0xFF

    if key == ord('q'):
        break

    if key == 32:
        started = True
        print("Started collecting...")

    if started and count < TOTAL_PHOTOS:
        path = f"{SAVE_DIR}/img_{count:04d}.jpg"
        cv2.imwrite(path, frame)
        count += 1
        print(f"Saved {count}/{TOTAL_PHOTOS}")
        time.sleep(DELAY)

    if count >= TOTAL_PHOTOS:
        print(f"Done! {TOTAL_PHOTOS} photos saved to {SAVE_DIR}/")
        break

cap.release()
cv2.destroyAllWindows()