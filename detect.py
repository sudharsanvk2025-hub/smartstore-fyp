import cv2
import os
import json
import time
import threading
import requests
import torch
from ultralytics import YOLO

MODEL_PATH     = "runs/detect/smartstore_v2/weights/best.pt"   # 6 products, trained 27 Oct
FLASK_URL      = "http://127.0.0.1:5000"
CAMERA_INDEX   = 0      # USB overhead webcam (1 = laptop camera)
CONFIDENCE     = 0.80   # needed to first register an item on the shelf
KEEP_CONF      = 0.45   # once on the shelf, still counts as there above this
CONFIRM_FRAMES = 10     # must be seen this many frames in a row to count as on the shelf
MISSING_SECS   = 3.0    # gone this long ...
MISSING_FRAMES = 8      # ... and for this many frames = picked up
IMG_SIZE       = 640    # same size it was trained at (GPU is fast enough)
ZONE_FILE      = "shelf_zone.json"   # the shelf area, set by pressing Z and dragging
STALL_SECS     = 2.0    # no new frame for this long = reopen camera

torch.set_num_threads(max(1, (torch.get_num_threads() or 4) // 2))
DEVICE = 0 if torch.cuda.is_available() else "cpu"
model = YOLO(MODEL_PATH)
print(f"Running YOLO on: {'GPU' if DEVICE == 0 else 'CPU'}")


class Camera:
    """Reads frames in the background, keeps only the newest, and restarts the camera if it freezes."""
    def __init__(self, index):
        self.index = index
        self.frame = None
        self.frame_id = 0
        self.last_frame_time = time.time()
        self.running = True
        self.lock = threading.Lock()
        self._open()
        threading.Thread(target=self._update, daemon=True).start()

    def _open(self):
        self.cap = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.last_frame_time = time.time()

    def _update(self):
        while self.running:
            ok, frame = self.cap.read()
            if ok:
                with self.lock:
                    self.frame = frame
                    self.frame_id += 1
                    self.last_frame_time = time.time()
            else:
                time.sleep(0.05)

    def restart(self):
        print("[CAMERA] No new frames, restarting camera...")
        try:
            self.cap.release()
        except Exception:
            pass
        time.sleep(0.5)
        self._open()

    def read(self):
        with self.lock:
            if self.frame is None:
                return None, 0
            return self.frame.copy(), self.frame_id

    def stalled(self):
        return time.time() - self.last_frame_time > STALL_SECS

    def release(self):
        self.running = False
        time.sleep(0.1)
        self.cap.release()


def send(route, item):
    """Tell app.py in a background thread so the video never freezes."""
    def _post():
        try:
            r = requests.post(f"{FLASK_URL}{route}", json={"name": item}, timeout=2)
            if r.ok:
                print(f"   -> app.py OK, basket total ${r.json().get('total', '?')}")
            else:
                print(f"   -> app.py error {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"[ERROR] Could not reach app.py: {e}")
    threading.Thread(target=_post, daemon=True).start()


# ─── Shelf zone: only products inside this rectangle count ───
def load_zone():
    try:
        with open(ZONE_FILE) as f:
            return tuple(json.load(f))
    except Exception:
        return None   # no zone yet = whole picture

zone = load_zone()
drawing = {"active": False, "start": None, "end": None}

def mouse(event, x, y, flags, param):
    global zone
    if not drawing["active"]:
        return
    if event == cv2.EVENT_LBUTTONDOWN:
        drawing["start"] = drawing["end"] = (x, y)
    elif event == cv2.EVENT_MOUSEMOVE and drawing["start"] and flags & cv2.EVENT_FLAG_LBUTTON:
        drawing["end"] = (x, y)
    elif event == cv2.EVENT_LBUTTONUP and drawing["start"]:
        (ax, ay), (bx, by) = drawing["start"], (x, y)
        if abs(bx - ax) > 20 and abs(by - ay) > 20:
            zone = (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
            with open(ZONE_FILE, "w") as f:
                json.dump(zone, f)
            print(f"[ZONE] Shelf zone saved: {zone}")
        drawing.update(active=False, start=None, end=None)

def in_zone(x1, y1, x2, y2):
    if zone is None:
        return True
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    return zone[0] <= cx <= zone[2] and zone[1] <= cy <= zone[3]


items = {}       # per item: on_shelf, last_seen time, frames missing, frames seen in a row
in_basket = []

cam = Camera(CAMERA_INDEX)
print("Waiting for camera...")
while cam.read()[0] is None:
    time.sleep(0.1)
print("Overhead detection running. Press Z to draw the shelf zone, Q to quit.")
if zone is None:
    print("[ZONE] No shelf zone yet, press Z and drag a box around the shelf")
cv2.namedWindow("SmartStore - Overhead Detection")
cv2.setMouseCallback("SmartStore - Overhead Detection", mouse)

last_id = 0
fps_count, fps_time = 0, time.time()

try:
    while True:
        if cam.stalled():
            cam.restart()
            continue

        frame, frame_id = cam.read()
        if frame is None or frame_id == last_id:
            if cv2.waitKey(5) & 0xFF == ord("q"):
                break
            continue
        last_id = frame_id

        results = model(frame, imgsz=IMG_SIZE, conf=KEEP_CONF, device=DEVICE, verbose=False)[0]
        now = time.time()
        seen = set()

        for box in results.boxes:
            name = model.names[int(box.cls[0])]
            conf = float(box.conf[0])
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            on_shelf_now = items.get(name, {}).get("on_shelf", False)
            # ignore: outside the shelf, or a new item that YOLO isn't sure about
            if not in_zone(x1, y1, x2, y2) or (not on_shelf_now and conf < CONFIDENCE):
                cv2.rectangle(frame, (x1, y1), (x2, y2), (128, 128, 128), 1)
                cv2.putText(frame, f"ignored {name} {conf:.0%}", (x1, y1 - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (128, 128, 128), 1)
                continue
            seen.add(name)
            colour = (0, 255, 0) if on_shelf_now else (0, 200, 255)   # yellow = still confirming
            cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 2)
            cv2.putText(frame, f"{name} {conf:.0%}", (x1, y1 - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, colour, 2)

        for name in seen:
            state = items.setdefault(name, {"on_shelf": False, "last_seen": now, "missing": 0, "streak": 0})
            state["last_seen"] = now
            state["missing"] = 0
            state["streak"] += 1
            # only believe it once it's been seen steadily (stops one-off false detections)
            if not state["on_shelf"] and state["streak"] >= CONFIRM_FRAMES:
                state["on_shelf"] = True
                if name in in_basket:
                    in_basket.remove(name)
                    print(f"[PUT BACK] {name} removed from basket")
                    send("/basket/remove", name)
                else:
                    print(f"[ON SHELF] {name}")

        for name, state in items.items():
            if name in seen:
                continue
            state["streak"] = 0
            if not state["on_shelf"]:
                continue
            state["missing"] += 1
            if now - state["last_seen"] > MISSING_SECS and state["missing"] >= MISSING_FRAMES:
                state["on_shelf"] = False
                in_basket.append(name)
                print(f"[PICKED UP] {name} added to basket")
                send("/basket/add", name)

        # shelf zone outline, and the box being drawn
        if zone:
            cv2.rectangle(frame, zone[:2], zone[2:], (255, 200, 0), 2)
            cv2.putText(frame, "SHELF", (zone[0] + 5, zone[1] + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 200, 0), 2)
        if drawing["active"]:
            cv2.putText(frame, "Drag a box around the shelf", (10, frame.shape[0] - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 200, 0), 2)
            if drawing["start"] and drawing["end"]:
                cv2.rectangle(frame, drawing["start"], drawing["end"], (255, 200, 0), 1)

        if in_basket:
            cv2.putText(frame, "IN BASKET: " + ", ".join(in_basket), (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)

        fps_count += 1
        if now - fps_time >= 5:
            print(f"[FPS] {fps_count / (now - fps_time):.1f}")
            fps_count, fps_time = 0, now

        cv2.imshow("SmartStore - Overhead Detection", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("z"):
            drawing.update(active=True, start=None, end=None)
            print("[ZONE] Drag a box around the shelf with the mouse")
finally:
    cam.release()
    cv2.destroyAllWindows()