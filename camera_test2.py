import cv2

print("Scanning for cameras...")

for i in range(3):
    cap = cv2.VideoCapture(i)
    if cap.isOpened():
        print(f"Camera {i} — FOUND")
        cap.release()
    else:
        print(f"Camera {i} — not found")

print("\nDone. Note which numbers show FOUND.")