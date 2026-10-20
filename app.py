# app.py
from flask import Flask, render_template, jsonify, request, session
from basket import add_item, remove_item, get_summary, clear_basket, get_basket
from inventory import get_inventory, get_low_stock
import db
import uuid
import time
import threading
from datetime import datetime

app = Flask(__name__)
app.secret_key = "smartstore-fyp-dev-key"   # needed for customer logins in the app

db.init_db()

AUTO_CHECKOUT_MINS = 5    # check out automatically after this long with no basket activity
MIN_STAY_SECS      = 10   # ignore the exit camera for this long after entering
TOP_UP_AMOUNTS     = (10, 20, 50)

# Active customer session (one customer in the store at a time)
current_customer = {
    "id":            None,   # customer id in the database (None = guest)
    "name":          None,
    "email":         None,
    "active":        False,
    "entry_time":    None,
    "visit_id":      None,
    "entered_at":    0,
    "last_activity": 0
}
checkout_lock = threading.Lock()

pending_payments = {}  # ref_id: session data (dashboard PayNow checkout)
pending_topups   = {}  # ref_id: {customer_id, amount} (wallet top-ups)
last_receipt     = {}  # customer_id: receipt shown on the phone after leaving
entry_blocked    = {}  # customer_id: reason the last check-in was refused

# Face registration started from the phone app (one at a time)
face_reg = {
    "customer_id": None,
    "status":      "idle",   # idle, waiting (for the Pi), capturing, done, failed
    "count":       0,
    "total":       20,
    "message":     "",
    "hint":        "",
    "updated":     0
}
REG_WAIT_LIMIT = 20   # seconds to wait for the Pi to pick up the job
REG_BUSY_LIMIT = 60   # after this long a stuck registration is cleared


def reset_customer():
    current_customer.update(id=None, name=None, email=None, active=False,
                            entry_time=None, visit_id=None, entered_at=0, last_activity=0)


def send_email(email, name, items, subtotal, gst, total, ref_id):
    try:
        from email_receipt import send_receipt
        send_receipt(customer_email=email, customer_name=name, items=items,
                     subtotal=subtotal, gst=gst, total=total, ref_id=ref_id)
        return True
    except Exception as e:
        print(f"[EMAIL] Could not send: {e}")
        return False


def checkout_customer(reason):
    """Customer is leaving: charge the wallet, save the visit, add points, send the receipt."""
    with checkout_lock:
        if not current_customer["active"]:
            return None
        customer_id = current_customer["id"]
        summary = get_summary()
        items, total = summary["items"], summary["total"]
        ref_id = str(uuid.uuid4())[:8].upper()

        receipt = {"ref_id": ref_id, "items": items, "subtotal": summary["subtotal"],
                   "gst": summary["gst"], "total": total, "reason": reason,
                   "time": datetime.now().strftime("%d %b %Y %H:%M"), "points": 0}

        if customer_id is None:
            # guest from the old dashboard flow, nothing to charge
            receipt["status"] = "guest"
        elif not items:
            db.finish_visit(current_customer["visit_id"], [], 0, ref_id, paid=True, reason=reason)
            receipt["status"] = "nothing_bought"
        elif db.charge(customer_id, total):
            receipt["points"] = db.finish_visit(current_customer["visit_id"], items, total, ref_id,
                                                paid=True, reason=reason)
            receipt["status"] = "paid"
            receipt["email_sent"] = send_email(current_customer["email"], current_customer["name"], items,
                                               summary["subtotal"], summary["gst"], total, ref_id)
        else:
            db.finish_visit(current_customer["visit_id"], items, total, ref_id, paid=False, reason=reason)
            receipt["status"] = "unpaid"

        print(f"[EXIT] {current_customer['name']} left ({reason}): {receipt['status']}, "
              f"${total:.2f}, +{receipt['points']} points")
        if customer_id is not None:
            receipt["shown_until"] = time.time() + 120
            last_receipt[customer_id] = receipt
        clear_basket()
        reset_customer()
        return receipt


def auto_checkout_loop():
    """Background check: customer inactive for too long, check them out."""
    while True:
        time.sleep(10)
        c = current_customer
        if c["active"] and time.time() - c["last_activity"] > AUTO_CHECKOUT_MINS * 60:
            checkout_customer("timeout")

threading.Thread(target=auto_checkout_loop, daemon=True).start()


# ─── Customer entry and exit (called by the Pi) ───
@app.route('/customer/entry', methods=['POST'])
def customer_entry():
    data = request.json or {}

    # The Pi can send a customer_id, or the old name + email
    customer = None
    if data.get("customer_id") is not None:
        customer = db.get_customer(data["customer_id"])
    elif data.get("email"):
        customer = db.get_customer_by_email(data["email"])

    # already inside: the entrance camera saw them again, keep their basket
    if current_customer["active"] and customer and current_customer["id"] == customer["id"]:
        return jsonify({"success": True, "message": "Already in store"})

    if current_customer["active"]:
        print(f"[ENTRY] Refused: {current_customer['name']} is still in the store")
        return jsonify({"success": False, "reason": "busy", "message": "Store busy, one customer at a time"}), 409

    if customer:
        if db.get_unpaid(customer["id"]):
            entry_blocked[customer["id"]] = "unpaid"
            print(f"[ENTRY] Refused: {customer['name']} has an unpaid bill")
            return jsonify({"success": False, "reason": "unpaid", "message": "Unpaid bill, please top up"}), 402
        entry_blocked.pop(customer["id"], None)
        last_receipt.pop(customer["id"], None)
        current_customer["id"]       = customer["id"]
        current_customer["name"]     = customer["name"]
        current_customer["email"]    = customer["email"]
        current_customer["visit_id"] = db.start_visit(customer["id"])
    else:
        # not signed up in the app yet, keep it working as a guest
        current_customer["id"]       = None
        current_customer["name"]     = data.get("name")
        current_customer["email"]    = data.get("email")
        current_customer["visit_id"] = None

    current_customer["active"]        = True
    current_customer["entry_time"]    = datetime.now().strftime("%H:%M")
    current_customer["entered_at"]    = time.time()
    current_customer["last_activity"] = time.time()
    clear_basket()
    print(f"[ENTRY] {current_customer['name']} entered (customer id {current_customer['id']})")
    return jsonify({"success": True, "message": f"Welcome {current_customer['name']}"})

@app.route('/customer/exit', methods=['POST'])
def customer_exit():
    """Exit camera on the Pi recognised someone leaving."""
    data = request.json or {}
    if not current_customer["active"] or current_customer["id"] != data.get("customer_id"):
        return jsonify({"success": False, "message": "That customer isn't in the store"})
    if time.time() - current_customer["entered_at"] < MIN_STAY_SECS:
        return jsonify({"success": False, "message": "Just entered, ignoring"})
    receipt = checkout_customer("exit_camera")
    return jsonify({"success": True, "status": receipt["status"]})

@app.route('/customer/status', methods=['GET'])
def customer_status():
    return jsonify(current_customer)


# ─── Basket routes (called by detect.py) ───
@app.route('/basket/add', methods=['POST'])
def basket_add():
    name = request.json.get("name")
    add_item(name)
    current_customer["last_activity"] = time.time()
    return jsonify(get_summary())

@app.route('/basket/remove', methods=['POST'])
def basket_remove():
    name = request.json.get("name")
    remove_item(name)
    current_customer["last_activity"] = time.time()
    return jsonify(get_summary())

@app.route('/basket', methods=['GET'])
def basket_get():
    return jsonify(get_summary())


# ─── Inventory route ───
@app.route('/inventory', methods=['GET'])
def inventory_get():
    inv = get_inventory()
    return jsonify({
        k: {
            "name":  v["name"],
            "price": v["price"],
            "stock": v["stock"]
        } for k, v in inv.items()
    })


# ─── Dashboard checkout + PayNow (still works for guests and testing) ───
@app.route('/checkout', methods=['POST'])
def checkout():
    if not current_customer["active"]:
        return jsonify({"error": "No active customer"}), 400

    summary = get_summary()
    if not summary["items"]:
        return jsonify({"error": "Basket is empty"}), 400

    ref_id = str(uuid.uuid4())[:8].upper()
    pending_payments[ref_id] = {
        "customer_id": current_customer["id"],
        "visit_id":    current_customer["visit_id"],
        "name":        current_customer["name"],
        "email":       current_customer["email"],
        "items":       summary["items"],
        "subtotal":    summary["subtotal"],
        "gst":         summary["gst"],
        "total":       summary["total"],
        "time":        datetime.now().strftime("%d %b %Y %H:%M")
    }

    return jsonify({
        "ref_id":   ref_id,
        "total":    summary["total"],
        "subtotal": summary["subtotal"],
        "gst":      summary["gst"],
        "customer": current_customer["name"]
    })

@app.route('/pay/confirm', methods=['POST'])
def pay_confirm():
    ref_id = request.json.get("ref_id")
    pay    = pending_payments.get(ref_id)

    if not pay:
        return jsonify({"error": "Invalid reference"}), 404

    email_sent = send_email(pay["email"], pay["name"], pay["items"], pay["subtotal"],
                            pay["gst"], pay["total"], ref_id)

    points = 0
    if pay["visit_id"]:
        points = db.finish_visit(pay["visit_id"], pay["items"], pay["total"], ref_id,
                                 paid=True, reason="paynow")
        last_receipt[pay["customer_id"]] = {
            "ref_id": ref_id, "items": pay["items"], "subtotal": pay["subtotal"], "gst": pay["gst"],
            "total": pay["total"], "reason": "paynow", "time": pay["time"], "points": points,
            "status": "paid", "email_sent": email_sent, "shown_until": time.time() + 120}

    clear_basket()
    reset_customer()
    del pending_payments[ref_id]

    print(f"[PAYMENT] {pay['name']} paid ${pay['total']} — ref {ref_id}, +{points} points")

    return jsonify({
        "success":       True,
        "ref_id":        ref_id,
        "total":         pay["total"],
        "email_sent":    email_sent,
        "points_earned": points
    })

@app.route('/payment/status/<ref_id>', methods=['GET'])
def payment_status(ref_id):
    paid = ref_id not in pending_payments
    return jsonify({"paid": paid})


# ─── Customer app (phone) ───
def logged_in_customer():
    customer_id = session.get("customer_id")
    return db.get_customer(customer_id) if customer_id else None

@app.route('/app')
def customer_app():
    return render_template('app.html')

@app.route('/api/signup', methods=['POST'])
def api_signup():
    data    = request.json or {}
    name    = (data.get("name") or "").strip()
    email   = (data.get("email") or "").strip()
    pin     = (data.get("pin") or "").strip()
    consent = bool(data.get("consent"))

    if not name or "@" not in email:
        return jsonify({"error": "Please enter your name and a valid email"}), 400
    if not (pin.isdigit() and 4 <= len(pin) <= 6):
        return jsonify({"error": "PIN must be 4 to 6 digits"}), 400
    if not consent:
        return jsonify({"error": "You need to agree to face recognition to use the store"}), 400

    customer_id = db.create_customer(name, email, pin, consent)
    if customer_id is None:
        return jsonify({"error": "An account with this email already exists"}), 400

    session["customer_id"] = customer_id
    print(f"[APP] New customer signed up: {name} (id {customer_id})")
    return jsonify({"success": True})

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json or {}
    customer = db.check_login(data.get("email", ""), (data.get("pin") or "").strip())
    if not customer:
        return jsonify({"error": "Wrong email or PIN"}), 401
    session["customer_id"] = customer["id"]
    return jsonify({"success": True})

@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.pop("customer_id", None)
    return jsonify({"success": True})

@app.route('/api/me', methods=['GET'])
def api_me():
    """Everything the phone app needs: account, wallet, check-in status, live basket, receipt, visits."""
    customer = logged_in_customer()
    if not customer:
        return jsonify({"logged_in": False})

    cid = customer["id"]
    in_store = current_customer["active"] and current_customer["id"] == cid
    check_reg_timeout()

    receipt = last_receipt.get(cid)
    if receipt and time.time() > receipt["shown_until"]:
        receipt = None

    unpaid = db.get_unpaid(cid)
    return jsonify({
        "logged_in":     True,
        "customer":      db.public(customer),
        "face_reg":      face_reg if face_reg["customer_id"] == cid else None,
        "in_store":      in_store,
        "entry_time":    current_customer["entry_time"] if in_store else None,
        "basket":        get_summary() if in_store else None,
        "receipt":       receipt,
        "unpaid_total":  round(sum(v["total"] for v in unpaid), 2),
        "entry_blocked": entry_blocked.get(cid),
        "top_up_amounts": TOP_UP_AMOUNTS,
        "visits":        db.get_visits(cid)
    })

@app.route('/api/leave', methods=['POST'])
def api_leave():
    """'I'm leaving' button in the app (backup if the exit camera misses them)."""
    customer = logged_in_customer()
    if not customer or not (current_customer["active"] and current_customer["id"] == customer["id"]):
        return jsonify({"error": "You're not checked in"}), 400
    receipt = checkout_customer("app_button")
    return jsonify({"success": True, "status": receipt["status"]})

@app.route('/api/topup', methods=['POST'])
def api_topup():
    """Start a simulated PayNow top-up."""
    customer = logged_in_customer()
    if not customer:
        return jsonify({"error": "Please log in first"}), 401
    amount = (request.json or {}).get("amount")
    if amount not in TOP_UP_AMOUNTS:
        return jsonify({"error": "Choose a top-up amount"}), 400
    ref_id = "TU" + str(uuid.uuid4())[:6].upper()
    pending_topups[ref_id] = {"customer_id": customer["id"], "amount": amount}
    return jsonify({"ref_id": ref_id, "amount": amount})

@app.route('/api/topup/confirm', methods=['POST'])
def api_topup_confirm():
    customer = logged_in_customer()
    ref_id = (request.json or {}).get("ref_id")
    t = pending_topups.get(ref_id)
    if not customer or not t or t["customer_id"] != customer["id"]:
        return jsonify({"error": "Invalid top-up"}), 400
    del pending_topups[ref_id]
    db.top_up(customer["id"], t["amount"])

    # pay any old unpaid bill straight away
    for v in db.pay_unpaid(customer["id"]):
        entry_blocked.pop(customer["id"], None)
        send_email(customer["email"], customer["name"], v["items"],
                   round(v["total"] / 1.09, 2), round(v["total"] - v["total"] / 1.09, 2), v["total"], v["ref_id"])
        print(f"[PAYMENT] {customer['name']} paid old bill ${v['total']:.2f} — ref {v['ref_id']}")

    print(f"[TOP UP] {customer['name']} topped up ${t['amount']}")
    return jsonify({"success": True, "wallet": db.get_customer(customer["id"])["wallet"]})


# ─── Face registration (phone app <-> Pi) ───
def set_reg(**kw):
    face_reg.update(kw)
    face_reg["updated"] = time.time()

def check_reg_timeout():
    age = time.time() - face_reg["updated"]
    if face_reg["status"] == "waiting" and age > REG_WAIT_LIMIT:
        set_reg(status="failed", message="The entrance camera isn't responding. Check that entry.py is running on the Pi.")
    elif face_reg["status"] == "capturing" and age > REG_BUSY_LIMIT:
        set_reg(status="failed", message="Registration timed out. Please try again.")

@app.route('/api/face/register', methods=['POST'])
def api_face_register():
    """Phone: 'register my face'. The Pi picks this up from /pi/task."""
    customer = logged_in_customer()
    if not customer:
        return jsonify({"error": "Please log in first"}), 401
    customer_id = customer["id"]
    check_reg_timeout()
    if face_reg["status"] in ("waiting", "capturing") and face_reg["customer_id"] != customer_id:
        return jsonify({"error": "Someone else is registering right now. Try again in a minute."}), 409
    set_reg(customer_id=customer_id, status="waiting", count=0, message="", hint="")
    print(f"[REGISTER] Customer {customer_id} asked to register their face")
    return jsonify({"success": True})

@app.route('/pi/task', methods=['GET'])
def pi_task():
    """Pi asks every second: is there a registration job for me?"""
    check_reg_timeout()
    if face_reg["status"] == "waiting":
        set_reg(status="capturing")
        return jsonify({"task": "register", "customer_id": face_reg["customer_id"]})
    return jsonify({"task": None})

@app.route('/pi/register/progress', methods=['POST'])
def pi_register_progress():
    data = request.json or {}
    if data.get("customer_id") == face_reg["customer_id"]:
        set_reg(count=data.get("count", 0), total=data.get("total", 20), hint=data.get("hint", ""))
    return jsonify({"success": True})

@app.route('/pi/register/done', methods=['POST'])
def pi_register_done():
    data = request.json or {}
    customer_id = data.get("customer_id")
    if data.get("success"):
        db.set_face_registered(customer_id, True)
        set_reg(status="done", message="")
        print(f"[REGISTER] Customer {customer_id} face registered")
    else:
        set_reg(status="failed", message=data.get("message", "Registration failed. Please try again."))
        print(f"[REGISTER] Customer {customer_id} registration failed")
    return jsonify({"success": True})


# ─── Dashboard ───
@app.route('/')
def dashboard():
    return render_template('dashboard.html')

# ─── Test route ───
@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "SmartStore running"})

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000, use_reloader=False)
