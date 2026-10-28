# entry.py - SmartStore entrance + exit cameras (Raspberry Pi 5)
# - Pi Camera = entrance (check in), USB webcam = exit (check out)
# - 7" HDMI screen at the entrance shows the camera view and instructions
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
import subprocess
import sys

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

SHOW_SCREEN  = True          # set False to run without the entrance screen
SCREEN_SIZE  = (1024, 600)   # most 7" HDMI screens are 1024x600
UNKNOWN_SECS = 2.5           # face seen but not matched for this long = "not recognised"

detector   = cv2.FaceDetectorYN.create(DET_MODEL, "", FRAME_SIZE, 0.6)
recognizer = cv2.FaceRecognizerSF.create(REC_MODEL, "")

GREEN  = (94, 197, 34)
RED    = (60, 60, 220)
AMBER  = (0, 170, 255)
BLUE   = (232, 87, 37)
WHITE  = (255, 255, 255)
DARK   = (30, 20, 20)


# ─── Entrance screen ───
class Screen:
    """Draws the camera view with a message banner on the 7" HDMI screen."""
    def __init__(self):
        self.enabled = False
        self.banner = None           # {"text", "sub", "color", "until"}
        if not SHOW_SCREEN:
            return
        # started over SSH: point the window at the screen plugged into the Pi
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            os.environ["DISPLAY"] = ":0"
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

        # OpenCV crashes the whole program if it can't open a window,
        # so test it in a separate process first
        test = "import cv2; cv2.namedWindow('t'); cv2.waitKey(1); cv2.destroyAllWindows()"
        try:
            ok = subprocess.run([sys.executable, "-c", test], capture_output=True, timeout=10).returncode == 0
        except Exception:
            ok = False
        if not ok:
            print("[SCREEN] Can't open a window on the Pi's screen, carrying on without it")
            print("         (check the screen is plugged in and the Pi has booted to the desktop)")
            return
        cv2.namedWindow("SmartStore", cv2.WINDOW_NORMAL)
        cv2.setWindowProperty("SmartStore", cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
        self.enabled = True
        print("[SCREEN] Entrance screen on")

    def flash(self, text, sub="", color=GREEN, secs=4):
        self.banner = {"text": text, "sub": sub, "color": color, "until": time.time() + secs}

    def render(self, frame, faces=(), face_color=GREEN, text=None, sub="", color=BLUE, progress=None):
        """Build the full screen image. A flash() banner overrides the normal text."""
        sw, sh = SCREEN_SIZE
        view = frame.copy()
        for f in faces:
            x, y, w, h = map(int, f[:4])
            cv2.rectangle(view, (x, y), (x + w, y + h), face_color, 3)
        view = cv2.flip(view, 1)   # mirror, so it feels like looking in a mirror

        # scale the camera image to fill the screen, crop the middle
        fh, fw = view.shape[:2]
        scale = max(sw / fw, sh / fh)
        view = cv2.resize(view, (int(fw * scale), int(fh * scale)))
        y0 = (view.shape[0] - sh) // 2
        x0 = (view.shape[1] - sw) // 2
        canvas = view[y0:y0 + sh, x0:x0 + sw].copy()

        # top bar
        overlay = canvas.copy()
        cv2.rectangle(overlay, (0, 0), (sw, 64), DARK, -1)
        canvas = cv2.addWeighted(overlay, 0.75, canvas, 0.25, 0)
        cv2.putText(canvas, "SmartStore  |  Entrance", (24, 43), cv2.FONT_HERSHEY_DUPLEX, 1.0, WHITE, 2, cv2.LINE_AA)
        clock = time.strftime("%H:%M")
        (tw, _), _ = cv2.getTextSize(clock, cv2.FONT_HERSHEY_DUPLEX, 1.0, 2)
        cv2.putText(canvas, clock, (sw - tw - 24, 43), cv2.FONT_HERSHEY_DUPLEX, 1.0, WHITE, 2, cv2.LINE_AA)

        b = self.banner if self.banner and time.time() < self.banner["until"] else None
        if b:
            text, sub, color = b["text"], b["sub"], b["color"]
        if not text:
            return canvas

        # bottom banner
        bh = 150 if progress is not None else 120
        overlay = canvas.copy()
        cv2.rectangle(overlay, (0, sh - bh), (sw, sh), color, -1)
        canvas = cv2.addWeighted(overlay, 0.85, canvas, 0.15, 0)
        self._centre(canvas, text, sh - bh + 52, 1.35, 2)
        if sub:
            self._centre(canvas, sub, sh - bh + 92, 0.8, 1)
        if progress is not None:
            done, total = progress
            px0, px1, py = 120, sw - 120, sh - 30
            cv2.rectangle(canvas, (px0, py - 10), (px1, py + 10), (60, 60, 60), -1)
            cv2.rectangle(canvas, (px0, py - 10), (px0 + int((px1 - px0) * done / total), py + 10), WHITE, -1)
        return canvas

    def _centre(self, img, text, y, size, thick):
        (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, size, thick)
        cv2.putText(img, text, ((img.shape[1] - tw) // 2, y), cv2.FONT_HERSHEY_DUPLEX, size, WHITE, thick, cv2.LINE_AA)

    def show(self, frame, **kw):
        if not self.enabled:
            return
        cv2.imshow("SmartStore", self.render(frame, **kw))
        cv2.waitKey(1)


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

def post(route, data, on_reply=None):
    """Send to the laptop in the background so the camera never freezes."""
    def _send():
        try:
            r = requests.post(f"{LAPTOP_URL}{route}", json=data, timeout=3)
            if on_reply:
                on_reply(r.json())
        except Exception as e:
            print(f"[ERROR] Could not reach laptop: {e}")
            if on_reply:
                on_reply({"success": False, "reason": "offline"})
    threading.Thread(target=_send, daemon=True).start()

def grab(picam):
    frame = picam.capture_array()
    return frame[:, :, :3] if frame.shape[2] == 4 else frame


def entry_reply(reply):
    """Show what the laptop said about the check-in on the entrance screen."""
    if reply.get("success"):
        msg = reply.get("message", "")
        if msg == "Already in store":
            screen.flash("You're already checked in", "Enjoy your shopping", GREEN, 3)
        else:
            name = msg.replace("Welcome", "").strip()
            screen.flash(f"Welcome, {name}!" if name else "Welcome!",
                         "Pick up what you need. Your basket is on your phone.", GREEN, 5)
    elif reply.get("reason") == "unpaid":
        screen.flash("Unpaid bill", "Please top up your wallet in the SmartStore app", RED, 5)
    elif reply.get("reason") == "busy":
        screen.flash("Please wait", "Another customer is shopping right now", AMBER, 4)
    else:
        screen.flash("Sorry, something went wrong", "The store system isn't responding", RED, 4)


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


# ─── Customer names (from the laptop, just for readable logs) ───
names = {}

def refresh_names():
    try:
        r = requests.get(f"{LAPTOP_URL}/pi/customers", timeout=2)
        names.update({int(k): v for k, v in r.json().items()})
    except Exception:
        pass

def who(cid):
    return f"{names[cid]} (#{cid})" if cid in names else f"customer #{cid}"


# ─── Check the laptop for registration jobs (runs in the background) ───
job = {"customer_id": None}

def poll_jobs():
    last_names = 0
    while True:
        if time.time() - last_names > 30:   # pick up new sign-ups now and then
            refresh_names()
            last_names = time.time()
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
    print(f"[REGISTER] Registering {who(customer_id)}. Look at the camera and move your head slightly.")
    folder = os.path.join(FACE_DB, str(customer_id))
    shutil.rmtree(folder, ignore_errors=True)   # re-registering replaces old photos
    os.makedirs(folder)

    tips = ["Look straight at the camera", "Turn your head slightly left",
            "Turn your head slightly right", "Tilt your chin up a little", "Look straight again"]
    count, start, last_msg = 0, time.time(), 0
    while count < NUM_PHOTOS and time.time() - start < REG_TIMEOUT:
        frame = grab(picam)
        _, all_faces = detector.detect(frame)
        reason, screen_hint, f = None, None, None
        if all_faces is None:
            reason, screen_hint = "no face in view", "Stand on the mark and look at the camera"
        else:
            f = max(all_faces, key=lambda f: f[2] * f[3])
            x, y, w, h = f[:4]
            if w < MIN_FACE:
                reason, screen_hint = f"face too small ({int(w)}px), come closer", "Come a little closer"
            elif x < 0 or y < 0 or x + w > FRAME_SIZE[0] or y + h > FRAME_SIZE[1]:
                reason, screen_hint = "face cut off at the edge, move back a little", "Move back a little"
            elif f[14] < REG_MIN_SCORE:
                reason = f"face not clear enough (score {f[14]:.2f}), face the camera in good light"
                screen_hint = "Face the camera in good light"

        if reason:
            screen.show(frame, faces=[f] if f is not None else [], face_color=AMBER,
                        text=f"Registering your face  {count}/{NUM_PHOTOS}", sub=screen_hint,
                        color=AMBER, progress=(count, NUM_PHOTOS))
            if time.time() - last_msg > 1:
                print(f"[REGISTER] Skipped: {reason}")
                post("/pi/register/progress", {"customer_id": customer_id, "count": count,
                                               "total": NUM_PHOTOS, "hint": reason})
                cv2.imwrite("reg_debug.jpg", frame)
                last_msg = time.time()
            time.sleep(0.05)
            continue

        aligned = recognizer.alignCrop(frame, f)
        cv2.imwrite(os.path.join(folder, f"face_{count:02d}.jpg"), aligned)
        count += 1
        print(f"[REGISTER] Captured {count}/{NUM_PHOTOS} (score {f[14]:.2f}, width {int(f[2])}px)")
        post("/pi/register/progress", {"customer_id": customer_id, "count": count, "total": NUM_PHOTOS, "hint": ""})

        # keep the screen moving during the short pause between photos
        tip = tips[min(count * len(tips) // NUM_PHOTOS, len(tips) - 1)]
        pause_end = time.time() + 0.3
        while time.time() < pause_end:
            screen.show(grab(picam), faces=[f], face_color=GREEN,
                        text=f"Registering your face  {count}/{NUM_PHOTOS}", sub=tip,
                        color=BLUE, progress=(count, NUM_PHOTOS))

    if count < NUM_PHOTOS:
        shutil.rmtree(folder, ignore_errors=True)
        known.pop(customer_id, None)
        print("[REGISTER] Failed, could not see the face clearly enough")
        screen.flash("Registration didn't work", "Tap 'Try again' in the app and face the camera in good light", RED, 6)
        post("/pi/register/done", {"customer_id": customer_id, "success": False,
                                   "message": "Couldn't see your face clearly. Face the camera in good light and try again."})
        return

    known[customer_id] = load_customer(customer_id)
    refresh_names()
    print(f"[REGISTER] {who(customer_id)} registered")
    screen.flash("Face registered!", "Step back, then walk up again to check in", GREEN, 5)
    post("/pi/register/done", {"customer_id": customer_id, "success": True})


# ─── Main ───
known = load_all()
refresh_names()
print(f"Loaded {len(known)} registered customer(s): {', '.join(who(c) for c in known)}")

picam = Picamera2()
picam.configure(picam.create_preview_configuration(main={"format": "RGB888", "size": FRAME_SIZE}))
picam.start()
time.sleep(2)

screen = Screen()
exit_cam = ExitCamera()
threading.Thread(target=poll_jobs, daemon=True).start()
print("Cameras running. Press Ctrl+C to stop.")

last_seen = {}       # last check-in message per customer
last_exit = {}       # last check-out message per customer
unknown_since = None # when an unrecognised face first appeared
try:
    while True:
        if job["customer_id"] is not None:
            cid = job["customer_id"]
            job["customer_id"] = None
            register(picam, cid, known)
            continue

        # entrance camera: check in
        frame = grab(picam)
        faces = find_faces(frame)
        matched_any = False
        for face in faces:
            if not known:
                break
            vec = embed(recognizer.alignCrop(frame, face))
            cid, score = best_match(vec, known)
            print(f"[IN]  {who(cid) if score >= THRESHOLD else f'unknown (closest: {who(cid)})'}, similarity {score:.2f}")
            if score >= THRESHOLD:
                matched_any = True
                if time.time() - last_seen.get(cid, 0) > COOLDOWN:
                    last_seen[cid] = time.time()
                    print(f"[IN]  Welcome {who(cid)}!")
                    screen.flash("Checking you in...", "", BLUE, 3)
                    post("/customer/entry", {"customer_id": cid}, on_reply=entry_reply)

        # face in view that nobody matches for a while: tell them to register
        if faces and not matched_any:
            unknown_since = unknown_since or time.time()
            if time.time() - unknown_since > UNKNOWN_SECS:
                screen.flash("Face not recognised", "New here? Sign up and register your face in the SmartStore app", AMBER, 3)
                unknown_since = time.time()
        else:
            unknown_since = None

        screen.show(frame, faces=faces, face_color=GREEN if matched_any or not faces else AMBER,
                    text="Look at the camera to check in", sub="Stand on the mark, about an arm's length away",
                    color=BLUE)

        # exit camera: check out
        frame = exit_cam.read()
        if frame is not None:
            for face in find_faces(frame):
                vec = embed(recognizer.alignCrop(frame, face))
                cid, score = best_match(vec, known) if known else (None, 0.0)
                print(f"[OUT] {who(cid) if score >= EXIT_THRESHOLD else f'unknown (closest: {who(cid)})'}, similarity {score:.2f}")
                if score >= EXIT_THRESHOLD and time.time() - last_exit.get(cid, 0) > EXIT_COOLDOWN:
                    last_exit[cid] = time.time()
                    last_seen[cid] = time.time()   # don't check them straight back in
                    print(f"[OUT] Goodbye {who(cid)}!")
                    post("/customer/exit", {"customer_id": cid})

        if not screen.enabled:
            time.sleep(0.2)   # with a screen, drawing it already slows the loop down
except KeyboardInterrupt:
    pass
finally:
    picam.stop()
    cv2.destroyAllWindows()
