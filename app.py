
from flask import (
    Flask, render_template, request, jsonify,
    send_file, session, redirect, url_for
)
import sqlite3
import hashlib
import qrcode
import io
import pickle
import os
from datetime import datetime
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

# =====================================
# FLASK CONFIGURATION
# =====================================

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "tourist.db")
MODEL_FILE = os.path.join(BASE_DIR, "tourist_risk_model.pkl")

app.secret_key = os.environ.get("FLASK_SECRET_KEY")

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

if not app.secret_key or not ADMIN_USERNAME or not ADMIN_PASSWORD:
    raise RuntimeError(
        "Set FLASK_SECRET_KEY, ADMIN_USERNAME and ADMIN_PASSWORD "
        "in the terminal before running the application."
    )

ADMIN_PASSWORD_HASH = generate_password_hash(ADMIN_PASSWORD)

# =====================================
# LOAD MACHINE LEARNING MODEL
# =====================================

if not os.path.exists(MODEL_FILE):
    raise FileNotFoundError("tourist_risk_model.pkl file not found.")

with open(MODEL_FILE, "rb") as file:
    model = pickle.load(file)

# =====================================
# DATABASE CONNECTION
# =====================================

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


# =====================================
# ADMIN LOGIN PROTECTION
# =====================================

def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return func(*args, **kwargs)
    return wrapper


# =====================================
# DATABASE CREATION AND MIGRATION
# =====================================

def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS tourists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            digital_id TEXT UNIQUE,
            created_at TEXT,
            emergency_contact_name TEXT,
            emergency_contact_phone TEXT
        )
    """)

    columns = [
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(tourists)"
        ).fetchall()
    ]

    if "emergency_contact_name" not in columns:
        conn.execute("""
            ALTER TABLE tourists
            ADD COLUMN emergency_contact_name TEXT
        """)

    if "emergency_contact_phone" not in columns:
        conn.execute("""
            ALTER TABLE tourists
            ADD COLUMN emergency_contact_phone TEXT
        """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sos_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tourist_id INTEGER NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            accuracy REAL,
            location_link TEXT,
            created_at TEXT,
            status TEXT DEFAULT 'NEW',
            admin_notification_status TEXT DEFAULT 'NOT_CONFIGURED',
            sms_status TEXT DEFAULT 'NOT_CONFIGURED',
            FOREIGN KEY (tourist_id) REFERENCES tourists(id)
        )
    """)

    conn.commit()
    conn.close()


# =====================================
# DIGITAL ID GENERATION
# =====================================

def generate_id(name, phone):
    unique_value = name + phone + datetime.now().isoformat()
    return hashlib.sha256(
        unique_value.encode()
    ).hexdigest()


# =====================================
# HOME PAGE
# =====================================

@app.route("/")
def home():
    return render_template("index.html")


# =====================================
# TOURIST REGISTRATION
# =====================================

@app.route("/register", methods=["POST"])
def register():

    data = request.get_json(silent=True) or request.form

    name = data.get("name", "").strip()
    phone = data.get("phone", "").strip()
    emergency_name = data.get(
        "emergency_contact_name", ""
    ).strip()
    emergency_phone = data.get(
        "emergency_contact_phone", ""
    ).strip()

    if not name or not phone or not emergency_name or not emergency_phone:
        return jsonify({"error": "All fields are required"}), 400

    if not phone.isdigit() or len(phone) != 10:
        return jsonify({
            "error": "Enter a valid 10-digit tourist phone number"
        }), 400

    if not emergency_phone.isdigit() or len(emergency_phone) != 10:
        return jsonify({
            "error": "Enter a valid 10-digit emergency contact number"
        }), 400

    if phone == emergency_phone:
        return jsonify({
            "error": "Emergency contact number must be different from tourist number"
        }), 400

    digital_id = generate_id(name, phone)
    created_at = datetime.now().isoformat(timespec="seconds")

    conn = get_db()

    try:
        cursor = conn.execute("""
            INSERT INTO tourists (
                name, phone, digital_id, created_at,
                emergency_contact_name, emergency_contact_phone
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            name,
            phone,
            digital_id,
            created_at,
            emergency_name,
            emergency_phone
        ))

        tourist_db_id = cursor.lastrowid
        conn.commit()

    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({
            "error": "Registration failed. Please try again."
        }), 400

    conn.close()

    qr_url = url_for(
        "generate_qr",
        tourist_id=digital_id
    )

    return jsonify({
        "message": "Registration successful",

        # Numeric Tourist ID
        "id": tourist_db_id,
        "tourist_id": tourist_db_id,

        # Tourist details
        "name": name,
        "emergency_contact_name": emergency_name,

        # Separate Digital ID
        "digital_id": digital_id,

        # QR Code
        "qr_code": qr_url,
        "qr_url": qr_url
    })


# =====================================
# QR CODE GENERATION
# =====================================

@app.route("/qr/<tourist_id>")
def generate_qr(tourist_id):

    conn = get_db()

    record = conn.execute("""
        SELECT digital_id
        FROM tourists
        WHERE digital_id = ?
    """, (tourist_id,)).fetchone()

    conn.close()

    if not record:
        return jsonify({"error": "Tourist not found"}), 404

    qr = qrcode.make(record["digital_id"])

    image_bytes = io.BytesIO()
    qr.save(image_bytes, format="PNG")
    image_bytes.seek(0)

    return send_file(
        image_bytes,
        mimetype="image/png",
        download_name="tourist_qr.png"
    )


# =====================================
# ADMIN LOGIN
# =====================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():

    if request.method == "POST":

        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if (
            username == ADMIN_USERNAME
            and check_password_hash(ADMIN_PASSWORD_HASH, password)
        ):
            session.clear()
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))

        return render_template(
            "admin_login.html",
            error="Invalid username or password"
        )

    return render_template("admin_login.html")


# =====================================
# ADMIN DASHBOARD
# =====================================

@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template("admin.html")


# =====================================
# ADMIN LOGOUT
# =====================================

@app.route("/admin/logout")
@admin_required
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))


# =====================================
# ADMIN TOURIST DATA
# =====================================

@app.route("/admin/tourists")
@admin_required
def admin_tourists():

    conn = get_db()

    records = conn.execute("""
        SELECT id, name, phone, created_at
        FROM tourists
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return jsonify([dict(row) for row in records])


# =====================================
# ADMIN SOS ALERT DATA
# =====================================

@app.route("/admin/alerts")
@admin_required
def admin_alerts():

    conn = get_db()

    records = conn.execute("""
        SELECT
            s.id,
            s.tourist_id,
            t.name AS tourist_name,
            s.created_at,
            s.location_link,
            s.status,
            s.sms_status,
            s.admin_notification_status
        FROM sos_alerts s
        JOIN tourists t ON s.tourist_id = t.id
        ORDER BY s.id DESC
    """).fetchall()

    conn.close()

    return jsonify([dict(row) for row in records])


# =====================================
# UPDATE SOS ALERT STATUS
# =====================================

@app.route("/admin/alert/<int:alert_id>/status", methods=["POST"])
@admin_required
def update_alert_status(alert_id):

    data = request.get_json(silent=True) or {}
    status = data.get("status")

    allowed_statuses = [
        "NEW",
        "ACKNOWLEDGED",
        "RESOLVED"
    ]

    if status not in allowed_statuses:
        return jsonify({"error": "Invalid status"}), 400

    conn = get_db()

    cursor = conn.execute("""
        UPDATE sos_alerts
        SET status = ?
        WHERE id = ?
    """, (status, alert_id))

    if cursor.rowcount == 0:
        conn.close()
        return jsonify({"error": "Alert not found"}), 404

    conn.commit()
    conn.close()

    return jsonify({
        "message": "Alert status updated successfully",
        "alert_id": alert_id,
        "status": status
    })


# =====================================
# SINGLE TOURIST DETAILS - ADMIN ONLY
# =====================================

@app.route("/tourist/<tourist_id>")
@admin_required
def tourist_details(tourist_id):

    conn = get_db()

    record = conn.execute("""
        SELECT *
        FROM tourists
        WHERE digital_id = ? OR CAST(id AS TEXT) = ?
    """, (tourist_id, tourist_id)).fetchone()

    conn.close()

    if not record:
        return jsonify({"error": "Tourist not found"}), 404

    return jsonify(dict(record))


# =====================================
# ALL TOURISTS - ADMIN ONLY
# =====================================

@app.route("/tourists")
@admin_required
def all_tourists():

    conn = get_db()

    records = conn.execute("""
        SELECT id, name, phone, digital_id, created_at
        FROM tourists
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return jsonify([dict(row) for row in records])


# =====================================
# SOS ALERT
# =====================================

@app.route("/sos", methods=["POST"])
def sos_alert():

    data = request.get_json(silent=True) or {}

    tourist_id = str(
        data.get("tourist_id", "")
    ).strip()

    if not tourist_id:
        return jsonify({
            "error": "Tourist ID is required"
        }), 400

    try:
        latitude = float(data.get("latitude"))
        longitude = float(data.get("longitude"))
        accuracy = float(data.get("accuracy", 0))

    except (TypeError, ValueError):
        return jsonify({
            "error": "Start GPS tracking before sending an SOS alert"
        }), 400

    if not (
        -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        return jsonify({
            "error": "Invalid GPS coordinates"
        }), 400

    if accuracy < 0:
        return jsonify({
            "error": "Invalid GPS accuracy"
        }), 400

    conn = get_db()

    # Accept numeric Tourist ID or SHA-256 Digital ID
    tourist = conn.execute("""
        SELECT id
        FROM tourists
        WHERE digital_id = ?
        OR CAST(id AS TEXT) = ?
    """, (tourist_id, tourist_id)).fetchone()

    if not tourist:
        conn.close()
        return jsonify({
            "error": "Tourist not found"
        }), 404

    db_tourist_id = tourist["id"]

    location_link = (
        f"https://www.google.com/maps?q={latitude},{longitude}"
    )

    created_at = datetime.now().isoformat(
        timespec="seconds"
    )

    cursor = conn.execute("""
        INSERT INTO sos_alerts (
            tourist_id,
            latitude,
            longitude,
            accuracy,
            location_link,
            created_at,
            status,
            admin_notification_status,
            sms_status
        )
        VALUES (?, ?, ?, ?, ?, ?, 'NEW',
                'NOT_CONFIGURED', 'NOT_CONFIGURED')
    """, (
        db_tourist_id,
        latitude,
        longitude,
        accuracy,
        location_link,
        created_at
    ))

    alert_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return jsonify({
        "message": "SOS alert saved successfully",
        "alert_id": alert_id,
        "tourist_id": db_tourist_id,
        "status": "NEW",
        "location_link": location_link,
        "admin_notification_status": "NOT_CONFIGURED",
        "sms_status": "NOT_CONFIGURED"
    })


# =====================================
# MACHINE LEARNING RISK PREDICTION
# =====================================

@app.route("/predict-risk", methods=["POST"])
def predict_risk():

    data = request.get_json(silent=True) or {}

    try:
        location_risk = float(data.get("location_risk"))
        night = int(data.get("night"))
        crowd_level = int(data.get("crowd_level"))
        incident_history = int(data.get("incident_history"))

    except (TypeError, ValueError):
        return jsonify({
            "error": "Please provide all four valid prediction inputs"
        }), 400

    if not (0 <= location_risk <= 10):
        return jsonify({
            "error": "Location risk must be between 0 and 10"
        }), 400

    if night not in [0, 1]:
        return jsonify({
            "error": "Night must be 0 or 1"
        }), 400

    if crowd_level not in [0, 1, 2]:
        return jsonify({
            "error": "Crowd level must be 0, 1 or 2"
        }), 400

    if not (0 <= incident_history <= 5):
        return jsonify({
            "error": "Incident history must be between 0 and 5"
        }), 400

    features = [[
        location_risk,
        night,
        crowd_level,
        incident_history
    ]]

    prediction = str(
        model.predict(features)[0]
    ).strip().upper()

    return jsonify({
        "risk_prediction": prediction,
        "risk_level": prediction,
        "message": "Prototype prediction based on the supplied inputs.",
        "input_features": {
            "location_risk": location_risk,
            "night": night,
            "crowd_level": crowd_level,
            "incident_history": incident_history
        }
    })


# =====================================
# RUN APPLICATION
# =====================================

if __name__ == "__main__":

    init_db()

    print("Database initialized successfully!")
    print("Smart Tourist Safety System is ready!")

    app.run(debug=True)
