# app.py
from flask import Flask, render_template, jsonify, request
from basket import add_item, remove_item, get_summary, clear_basket, get_basket
from inventory import get_inventory, get_low_stock
import uuid
from datetime import datetime

app = Flask(__name__)

# Active customer session
current_customer = {
    "name": None,
    "email": None,
    "active": False,
    "entry_time": None
}

pending_payments = {}  # ref_id: session data

# ─── Customer entry (called by Pi later, manual for now) ───
@app.route('/customer/entry', methods=['POST'])
def customer_entry():
    data = request.json
    current_customer["name"]       = data.get("name")
    current_customer["email"]      = data.get("email")
    current_customer["active"]     = True
    current_customer["entry_time"] = datetime.now().strftime("%H:%M")
    clear_basket()
    print(f"[ENTRY] {current_customer['name']} entered")
    return jsonify({"success": True, "message": f"Welcome {current_customer['name']}"})

@app.route('/customer/status', methods=['GET'])
def customer_status():
    return jsonify(current_customer)

# ─── Basket routes ───
@app.route('/basket/add', methods=['POST'])
def basket_add():
    name = request.json.get("name")
    add_item(name)
    return jsonify(get_summary())

@app.route('/basket/remove', methods=['POST'])
def basket_remove():
    name = request.json.get("name")
    remove_item(name)
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

# ─── Checkout + payment ───
@app.route('/checkout', methods=['POST'])
def checkout():
    if not current_customer["active"]:
        return jsonify({"error": "No active customer"}), 400

    summary = get_summary()
    if not summary["items"]:
        return jsonify({"error": "Basket is empty"}), 400

    ref_id = str(uuid.uuid4())[:8].upper()
    pending_payments[ref_id] = {
        "name":     current_customer["name"],
        "email":    current_customer["email"],
        "items":    summary["items"],
        "subtotal": summary["subtotal"],
        "gst":      summary["gst"],
        "total":    summary["total"],
        "time":     datetime.now().strftime("%d %b %Y %H:%M")
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
    ref_id  = request.json.get("ref_id")
    session = pending_payments.get(ref_id)

    if not session:
        return jsonify({"error": "Invalid reference"}), 404

    # Send email receipt
    try:
        from email_receipt import send_receipt
        send_receipt(
            customer_email = session["email"],
            customer_name  = session["name"],
            items          = session["items"],
            subtotal       = session["subtotal"],
            gst            = session["gst"],
            total          = session["total"],
            ref_id         = ref_id
        )
        email_sent = True
    except Exception as e:
        print(f"[EMAIL] Could not send: {e}")
        email_sent = False

    # Reset session
    clear_basket()
    current_customer["active"] = False
    del pending_payments[ref_id]

    print(f"[PAYMENT] {session['name']} paid ${session['total']} — ref {ref_id}")

    return jsonify({
        "success":    True,
        "ref_id":     ref_id,
        "total":      session["total"],
        "email_sent": email_sent
    })

@app.route('/payment/status/<ref_id>', methods=['GET'])
def payment_status(ref_id):
    paid = ref_id not in pending_payments
    return jsonify({"paid": paid})

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