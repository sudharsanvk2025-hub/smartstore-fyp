import cv2
import os
import sys
import time

# Usage:  python collect_photos.py coke_can
#         python collect_photos.py mixed      (several products in one shot)
#
# SPACE = start / pause burst mode (one photo every DELAY seconds)
# C     = take one photo
# Q     = quit
# Photos are numbered on from what's already in the folder, so you can
# run it again later (different lighting, positions) without overwriting.

CAMERA_INDEX = 2        # USB overhead webcam (1 = laptop camera, found with cam_find.py)
TARGET       = 100      # new photos to take in this session
DELAY        = 0.4      # seconds between burst photos, move the product between shots

if len(sys.argv) < 2:
    print("Usage: python collect_photos.py <product_name>   e.g. python collect_photos.py coke_can")
    sys.exit()

PRODUCT_NAME = sys.argv[1].strip().lower()
SAVE_DIR     = os.path.join("dataset", PRODUCT_NAME)
os.makedirs(SAVE_DIR, exist_ok=True)

existing = [f for f in os.listdir(SAVE_DIR) if f.endswith(".jpg")]
already = len(existing)
count = 0               # new photos this session
next_num = max([int(f[4:8]) for f in existing if f[4:8].isdigit()] + [-1]) + 1

cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
if not cap.isOpened():
    print(f"ERROR: Cannot open camera {CAMERA_INDEX}. Try CAMERA_INDEX = 0")
    sys.exit()

print(f"Collecting photos for '{PRODUCT_NAME}' ({already} already in {SAVE_DIR}, taking {TARGET} more)")
print("SPACE = start/pause burst, C = single photo, Q = quit")

burst, last_shot, flash_until = False, 0, 0

def save(frame):
    global count, next_num, flash_until
    path = os.path.join(SAVE_DIR, f"img_{next_num:04d}.jpg")
    cv2.imwrite(path, frame)
    count += 1
    next_num += 1
    flash_until = time.time() + 0.15
    print(f"Saved {count}/{TARGET}  ({already + count} total)  {path}")

while True:
    ok, frame = cap.read()
    if not ok:
        continue

    now = time.time()
    if burst and now - last_shot >= DELAY:
        save(frame)
        last_shot = now
        if count >= TARGET:
            burst = False
            print(f"Reached {TARGET} photos for {PRODUCT_NAME}. Press Q to finish or keep going.")

    display = frame.copy()
    if now < flash_until:
        cv2.rectangle(display, (0, 0), (display.shape[1] - 1, display.shape[0] - 1), (255, 255, 255), 12)
    status = "BURST ON - move the product" if burst else "Paused - SPACE to start"
    color = (0, 200, 0) if burst else (0, 165, 255)
    cv2.putText(display, f"{PRODUCT_NAME}: {count}/{TARGET} new ({already + count} total)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    cv2.putText(display, status, (10, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    cv2.imshow("Photo Collection", display)

    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    if key == 32:
        burst = not burst
        print("Burst on" if burst else "Paused")
    if key == ord("c"):
        save(frame)

cap.release()
cv2.destroyAllWindows()
print(f"Done. {count} new photos, {already + count} total in {SAVE_DIR}/")
