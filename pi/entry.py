# entry.py - SmartStore entrance + exit cameras (Raspberry Pi 5)
# - Pi Camera = entrance (check in), USB webcam = exit (check out)
# - YuNet finds faces, SFace recognises them
# - face_db/<customer id>/ holds each customer's face photos
# - registration is started from the phone app: this script checks the laptop for jobs
from picamera2 import Picamera2
import cv2
import numpy as np
import os
import time
import shutil
import threading
import requests
import glob

LAPTOP_URL   = "http://172.20.10.2:5000"   # <-- your laptop's IP
FACE_DB      = "face_db"
DET_MODEL    = "face_detection_yunet_2023mar.onnx"
REC_MODEL    = "face_recognition_sface_2021dec.onnx"

THRESHOLD    = 0.45   # similarity 0 to 1, HIGHER = better match (opposite of LBPH)
COOLDOWN     = 15     # seconds before the same customer can check in again
EXIT_THRESHOLD = 0.40 # exit camera is a different camera, so allow a slightly lower match
EXIT_COOLDOWN  = 15   # seconds between exit messages for the same customer
NUM_PHOTOS   = 20     # photos taken when registering
REG_TIMEOUT  = 45     # give up registering after this many seconds
MIN_FACE     = 60     # ignore faces smaller than this (pixels), too far away
REG_MIN_SCORE = 0.75  # how sure YuNet must be that it's a clear face when registering
FRAME_SIZE   = (640, 480)

detector   = cv2.FaceDetectorYN.create(DET_MODEL, "", FRAME_SIZE, 0.6)
recognizer = cv2.FaceRecognizerSF.create(REC_MODEL, "")


# ─── Helpers ───
def find_faces(frame):
    """Return the faces YuNet finds, biggest first. Each row: x, y, w, h, 10 landmark values, score."""
    _, faces = detector.detect(frame)
    if faces is None:
        return []
    faces = [f for f in faces if f[2] >= MIN_FACE]
    return sorted(faces, key=lambda f: f[2] * f[3], reverse=True)

def embed(aligned):
    """Turn an aligned 112x112 face into a normalised 128-number fingerprint."""
    v = recognizer.feature(aligned).flatten()
    return v / np.linalg.norm(v)

def load_customer(customer_id):
    folder = os.path.join(FACE_DB, str(customer_id))
    vecs = []
    for f in sorted(os.listdir(folder)):
        img = cv2.imread(os.path.join(folder, f))
        if img is not None:
            vecs.append(embed(img))
    return np.array(vecs) if vecs else None

def load_all():
    known = {}
    os.makedirs(FACE_DB, exist_ok=True)
    for name in sorted(os.listdir(FACE_DB)):
        if not os.path.isdir(os.path.join(FACE_DB, name)):
            continue
        if not name.isdigit():
            print(f"Skipping old folder '{name}' (not a customer ID), you can delete it")
            continue
        vecs = load_customer(int(name))
        if vecs is not None:
            known[int(name)] = vecs
    return known

def best_match(vec, known):
    """Compare one face to every customer. Score = average of the 3 closest photos."""
    best_id, best_score = None, 0.0
    for cid, vecs in known.items():
        sims = np.sort(vecs @ vec)[::-1]
        score = float(sims[:3].mean())
        if score > best_score:
            best_id, best_score = cid, score
    return best_id, best_score

def post(route, data):
    """Send to the laptop in the background so the camera never freezes."""
    def _send():
        try:
            requests.post(f"{LAPTOP_URL}{route}", json=data, timeout=3)
        except Exception as e:
            print(f"[ERROR] Could not reach laptop: {e}")
    threading.Thread(target=_send, daemon=True).start()

def grab(picam):
    frame = picam.capture_array()
    return frame[:, :, :3] if frame.shape[2] == 4 else frame


# ─── Exit camera (USB webcam) ───
class ExitCamera:
    """Finds the USB webcam and keeps the newest frame in the background."""
    def __init__(self):
        devices = sorted(glob.glob("/dev/v4l/by-id/usb-*-video-index0"))
        self.cap = None
        self.frame = None
        if not devices:
            print("[EXIT] No USB webcam found, exit camera is off (the app's 'I'm leaving' button still works)")
            return
        self.cap = cv2.VideoCapture(devices[0], cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_SIZE[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_SIZE[1])
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self.cap.isOpened():
            print(f"[EXIT] Could not open {devices[0]}, exit camera is off")
            self.cap = None
            return
        print(f"[EXIT] Exit camera: {devices[0]}")
        self.lock = threading.Lock()
        threading.Thread(target=self._update, daemon=True).start()

    def _update(self):
        while True:
            ok, frame = self.cap.read()
            if ok:
                if (frame.shape[1], frame.shape[0]) != FRAME_SIZE:
                    frame = cv2.resize(frame, FRAME_SIZE)
                with self.lock:
                    self.frame = frame
            else:
                time.sleep(0.05)

    def read(self):
        if self.cap is None:
            return None
        with self.lock:
            f, self.frame = self.frame, None   # each frame is only checked once
            return f


# ─── Check the laptop for registration jobs (runs in the background) ───
job = {"customer_id": None}

def poll_jobs():
    while True:
        try:
            r = requests.get(f"{LAPTOP_URL}/pi/task", timeout=2)
            task = r.json()
            if task.get("task") == "register":
                job["customer_id"] = task["customer_id"]
        except Exception:
            pass
        time.sleep(1)


# ─── Registration ───
def register(picam, customer_id, known):
    print(f"[REGISTER] Registering customer {customer_id}. Look at the camera and move your head slightly.")
    folder = os.path.join(FACE_DB, str(customer_id))
    shutil.rmtree(folder, ignore_errors=True)   # re-registering replaces old photos
    os.makedirs(folder)

    count, start, last_msg = 0, time.time(), 0
    while count < NUM_PHOTOS and time.time() - start < REG_TIMEOUT:
        frame = grab(picam)
        _, all_faces = detector.detect(frame)
        reason = None
        if all_faces is None:
            reason = "no face in view"
        else:
            f = max(all_faces, key=lambda f: f[2] * f[3])
            x, y, w, h = f[:4]
            if w < MIN_FACE:
                reason = f"face too small ({int(w)}px), come closer"
            elif x < 0 or y < 0 or x + w > FRAME_SIZE[0] or y + h > FRAME_SIZE[1]:
                reason = "face cut off at the edge, move back a little"
            elif f[14] < REG_MIN_SCORE:
                reason = f"face not clear enough (score {f[14]:.2f}), face the camera in good light"
        if reason:
            if time.time() - last_msg > 1:
                print(f"[REGISTER] Skipped: {reason}")
                post("/pi/register/progress", {"customer_id": customer_id, "count": count,
                                               "total": NUM_PHOTOS, "hint": reason})
                cv2.imwrite("reg_debug.jpg", frame)
                last_msg = time.time()
            time.sleep(0.1)
            continue
        faces = [f]
        aligned = recognizer.alignCrop(frame, faces[0])
        cv2.imwrite(os.path.join(folder, f"face_{count:02d}.jpg"), aligned)
        count += 1
        print(f"[REGISTER] Captured {count}/{NUM_PHOTOS} (score {faces[0][14]:.2f}, width {int(faces[0][2])}px)")
        post("/pi/register/progress", {"customer_id": customer_id, "count": count, "total": NUM_PHOTOS, "hint": ""})
        time.sleep(0.3)

    if count < NUM_PHOTOS:
        shutil.rmtree(folder, ignore_errors=True)
        known.pop(customer_id, None)
        print("[REGISTER] Failed, could not see the face clearly enough")
        post("/pi/register/done", {"customer_id": customer_id, "success": False,
                                   "message": "Couldn't see your face clearly. Face the camera in good light and try again."})
        return

    known[customer_id] = load_customer(customer_id)
    print(f"[REGISTER] Customer {customer_id} registered")
    post("/pi/register/done", {"customer_id": customer_id, "success": True})


# ─── Main ───
known = load_all()
print(f"Loaded {len(known)} registered customer(s): {list(known.keys())}")

picam = Picamera2()
picam.configure(picam.create_preview_configuration(main={"format": "RGB888", "size": FRAME_SIZE}))
picam.start()
time.sleep(2)

exit_cam = ExitCamera()
threading.Thread(target=poll_jobs, daemon=True).start()
print("Cameras running. Press Ctrl+C to stop.")

last_seen = {}   # last check-in message per customer
last_exit = {}   # last check-out message per customer
try:
    while True:
        if job["customer_id"] is not None:
            cid = job["customer_id"]
            job["customer_id"] = None
            register(picam, cid, known)
            continue

        if not known:
            time.sleep(0.5)
            continue

        # entrance camera: check in
        frame = grab(picam)
        for face in find_faces(frame):
            vec = embed(recognizer.alignCrop(frame, face))
            cid, score = best_match(vec, known)
            print(f"[IN]  best match customer {cid}, similarity {score:.2f}")
            if score >= THRESHOLD and time.time() - last_seen.get(cid, 0) > COOLDOWN:
                last_seen[cid] = time.time()
                print(f"[IN]  Welcome customer {cid}!")
                post("/customer/entry", {"customer_id": cid})

        # exit camera: check out
        frame = exit_cam.read()
        if frame is not None:
            for face in find_faces(frame):
                vec = embed(recognizer.alignCrop(frame, face))
                cid, score = best_match(vec, known)
                print(f"[OUT] best match customer {cid}, similarity {score:.2f}")
                if score >= EXIT_THRESHOLD and time.time() - last_exit.get(cid, 0) > EXIT_COOLDOWN:
                    last_exit[cid] = time.time()
                    last_seen[cid] = time.time()   # don't check them straight back in
                    print(f"[OUT] Goodbye customer {cid}!")
                    post("/customer/exit", {"customer_id": cid})
        time.sleep(0.2)
except KeyboardInterrupt:
    pass
finally:
    picam.stop()
