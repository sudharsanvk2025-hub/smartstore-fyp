# email_receipt.py
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

# ── Configure these two lines ──
SENDER_EMAIL = "sudharsanvk41@gmail.com"      # replace with your Gmail
SENDER_PASSWORD = "bkkb dmtb nwsd qjbc"    # replace with your App Password

def send_receipt(customer_email, customer_name, items, subtotal, gst, total, ref_id):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your SmartStore Receipt — Ref {ref_id}"
    msg["From"]    = SENDER_EMAIL
    msg["To"]      = customer_email

    # Build items rows
    items_html = "".join([
        f"""<tr>
              <td style="padding:10px;border-bottom:1px solid #f0f0f0">{item['name']}</td>
              <td style="padding:10px;border-bottom:1px solid #f0f0f0;text-align:center">{item['qty']}</td>
              <td style="padding:10px;border-bottom:1px solid #f0f0f0;text-align:right">
                S${item['price'] * item['qty']:.2f}
              </td>
            </tr>"""
        for item in items
    ])

    html = f"""
    <html>
    <body style="margin:0;padding:0;background:#f4f4f4;font-family:Arial,sans-serif">
      <div style="max-width:480px;margin:30px auto;background:#ffffff;
                  border-radius:16px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08)">

        <!-- Header -->
        <div style="background:#1a1a2e;padding:28px;text-align:center">
          <h1 style="color:#ffffff;margin:0;font-size:22px">🏪 SmartStore</h1>
          <p style="color:#9ca3af;margin:6px 0 0;font-size:13px">AI-Powered Cashierless Store</p>
        </div>

        <!-- Thank you -->
        <div style="padding:24px;text-align:center;border-bottom:1px solid #f0f0f0">
          <div style="font-size:36px;margin-bottom:8px">✅</div>
          <h2 style="color:#16a34a;margin:0 0 4px">Payment Confirmed</h2>
          <p style="color:#6b7280;font-size:13px;margin:0">
            Thank you, {customer_name}!
          </p>
        </div>

        <!-- Receipt details -->
        <div style="padding:20px 24px">
          <div style="display:flex;justify-content:space-between;margin-bottom:12px">
            <span style="color:#6b7280;font-size:13px">Reference</span>
            <span style="font-weight:bold;font-size:13px">SS-{ref_id}</span>
          </div>
          <div style="display:flex;justify-content:space-between;margin-bottom:12px">
            <span style="color:#6b7280;font-size:13px">Date & Time</span>
            <span style="font-size:13px">{datetime.now().strftime("%d %b %Y %H:%M")}</span>
          </div>
          <div style="display:flex;justify-content:space-between;margin-bottom:12px">
            <span style="color:#6b7280;font-size:13px">Payment</span>
            <span style="font-size:13px">PayNow (simulated)</span>
          </div>
        </div>

        <!-- Items table -->
        <div style="padding:0 24px">
          <table style="width:100%;border-collapse:collapse">
            <thead>
              <tr style="background:#f9fafb">
                <th style="padding:10px;text-align:left;font-size:12px;
                           color:#6b7280;font-weight:600">ITEM</th>
                <th style="padding:10px;text-align:center;font-size:12px;
                           color:#6b7280;font-weight:600">QTY</th>
                <th style="padding:10px;text-align:right;font-size:12px;
                           color:#6b7280;font-weight:600">SUBTOTAL</th>
              </tr>
            </thead>
            <tbody>
              {items_html}
            </tbody>
          </table>
        </div>

        <!-- Totals -->
        <div style="padding:16px 24px;border-top:1px solid #f0f0f0">
          <div style="display:flex;justify-content:space-between;margin-bottom:6px">
            <span style="color:#6b7280;font-size:13px">Subtotal</span>
            <span style="font-size:13px">S${subtotal:.2f}</span>
          </div>
          <div style="display:flex;justify-content:space-between;margin-bottom:16px">
            <span style="color:#6b7280;font-size:13px">GST (9%)</span>
            <span style="font-size:13px">S${gst:.2f}</span>
          </div>
          <div style="display:flex;justify-content:space-between;
                      padding-top:12px;border-top:2px solid #1a1a2e">
            <span style="font-weight:bold;font-size:16px">Total Paid</span>
            <span style="font-weight:bold;font-size:20px;color:#16a34a">S${total:.2f}</span>
          </div>
        </div>

        <!-- Footer -->
        <div style="background:#f9fafb;padding:20px;text-align:center;
                    border-top:1px solid #f0f0f0">
          <p style="color:#9ca3af;font-size:12px;margin:0">
            Thank you for shopping at SmartStore<br>
            Powered by YOLOv8 + DeepFace
          </p>
        </div>

      </div>
    </body>
    </html>
    """

    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, customer_email, msg.as_string())
            print(f"[EMAIL] Receipt sent to {customer_email}")
            return True
    except Exception as e:
        print(f"[EMAIL] Failed: {e}")
        return False

# Quick test
if __name__ == "__main__":
    print("Sending test receipt...")
    send_receipt(
        customer_email = SENDER_EMAIL,  # sends to yourself as a test
        customer_name  = "Test Customer",
        items = [
            {"name": "Coke Can",   "price": 1.50, "qty": 1},
            {"name": "Lays Chips", "price": 2.20, "qty": 2},
        ],
        subtotal = 5.90,
        gst      = 0.53,
        total    = 6.43,
        ref_id   = "TEST001"
    )