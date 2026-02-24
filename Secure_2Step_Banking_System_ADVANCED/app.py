from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
import random
import hashlib
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from functools import wraps

app = Flask(__name__)
app.secret_key = "super_secret_key_123"

DB_NAME = "database.db"

# ================= EMAIL CONFIG =================

SENDER_EMAIL = "k.saravanan0030@gmail.com"
SENDER_PASSWORD = "hrgdsfafefqynnvo"


def send_email(receiver, subject, body):
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = SENDER_EMAIL
        msg["To"] = receiver

        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, receiver, msg.as_string())
        server.quit()

        print("Email sent to", receiver)
        return True

    except Exception as e:
        print("Email Error:", e)
        return False


# ================= DATABASE =================

def db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():

    conn = db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_number TEXT UNIQUE,
        name TEXT,
        email TEXT UNIQUE,
        password TEXT,
        balance REAL DEFAULT 0,
        role TEXT DEFAULT 'user',
        full_name TEXT,
        phone TEXT,
        address TEXT,
        aadhaar TEXT,
        approval_status TEXT DEFAULT 'pending',
        otp_hash TEXT,
        otp_expiry TEXT,
        last_login TEXT
    )
    """)

    # Create Admin
    admin_email = "admin@bank.com"
    admin_pw = hashlib.sha256("admin123".encode()).hexdigest()

    admin = c.execute(
        "SELECT * FROM users WHERE email=?",
        (admin_email,)
    ).fetchone()

    if not admin:
        c.execute("""
        INSERT INTO users
        (account_number,name,email,password,role,approval_status,last_login)
        VALUES (?,?,?,?,?,?,?)
        """, (
            "0000000000",
            "System Admin",
            admin_email,
            admin_pw,
            "admin",
            "approved",
            datetime.now().isoformat()  # IMPORTANT → skip OTP
        ))

    conn.commit()
    conn.close()


init_db()


# ================= UTILITIES =================

def hash_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def generate_account():
    return str(random.randint(1000000000, 9999999999))


def generate_otp():
    return str(random.randint(100000, 999999))


def roles_allowed(*roles):
    def wrapper(f):

        @wraps(f)
        def decorated(*args, **kwargs):

            if "user" not in session:
                flash("Login required")
                return redirect("/login")

            if session["role"] not in roles:
                flash("Access denied")
                return redirect("/login")

            return f(*args, **kwargs)

        return decorated
    return wrapper


# ================= HOME =================

@app.route("/")
def home():

    if "user" not in session:
        return redirect("/login")

    conn = db()

    user = conn.execute("""
    SELECT role,approval_status,full_name
    FROM users WHERE email=?
    """, (session["user"],)).fetchone()

    conn.close()

    if user["role"] == "admin":
        return redirect("/admin_dashboard")

    if not user["full_name"]:
        return redirect("/create_profile")

    if user["approval_status"] != "approved":
        return redirect("/waiting")

    return redirect("/user_dashboard")


# ================= REGISTER =================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"]
        email = request.form["email"]
        password = hash_text(request.form["password"])

        acc = generate_account()

        conn = db()

        try:

            conn.execute("""
            INSERT INTO users
            (account_number,name,email,password,last_login)
            VALUES (?,?,?,?,?)
            """, (
                acc,
                name,
                email,
                password,
                None  # OTP required first login
            ))

            conn.commit()

            flash("Registration Successful")

            return redirect("/login")

        except:

            flash("Email already exists")

        conn.close()

    return render_template("register.html")


# ================= LOGIN =================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = hash_text(request.form["password"])

        conn = db()

        user = conn.execute("""
        SELECT email,password,last_login,role
        FROM users WHERE email=?
        """, (email,)).fetchone()

        if not user:
            flash("User not found")
            return redirect("/login")

        if password != user["password"]:
            flash("Invalid password")
            return redirect("/login")

        # ✅ ADMIN LOGIN → NO OTP
        if user["role"] == "admin":

            session.clear()

            session["user"] = user["email"]
            session["role"] = "admin"

            flash("Admin login success")

            return redirect("/admin_dashboard")

        # ✅ FIRST TIME USER LOGIN → OTP
        if not user["last_login"]:

            otp = generate_otp()

            conn.execute("""
            UPDATE users SET otp_hash=?, otp_expiry=?
            WHERE email=?
            """, (
                hash_text(otp),
                (datetime.now()+timedelta(minutes=5)).isoformat(),
                email
            ))

            conn.commit()

            send_email(
                email,
                "Bank OTP",
                f"Your OTP is {otp}"
            )

            session["temp_user"] = email

            flash("OTP sent")

            return redirect("/otp")

        # ✅ NORMAL LOGIN
        session.clear()

        session["user"] = email
        session["role"] = user["role"]

        flash("Login success")

        return redirect("/")

    return render_template("login.html")


# ================= OTP =================

@app.route("/otp", methods=["GET", "POST"])
def otp():

    if "temp_user" not in session:
        return redirect("/login")

    if request.method == "POST":

        entered = hash_text(request.form["otp"])

        conn = db()

        user = conn.execute("""
        SELECT otp_hash,email,role
        FROM users WHERE email=?
        """, (session["temp_user"],)).fetchone()

        if entered == user["otp_hash"]:

            session.clear()

            session["user"] = user["email"]
            session["role"] = user["role"]

            conn.execute("""
            UPDATE users SET last_login=?
            WHERE email=?
            """, (
                datetime.now().isoformat(),
                user["email"]
            ))

            conn.commit()

            flash("Login success")

            return redirect("/")

        flash("Invalid OTP")

    return render_template("otp.html")


# ================= RESEND OTP =================

@app.route("/resend_otp")
def resend_otp():

    if "temp_user" not in session:
        return redirect("/login")

    email = session["temp_user"]

    otp = generate_otp()

    conn = db()

    conn.execute("""
    UPDATE users SET otp_hash=?, otp_expiry=?
    WHERE email=?
    """, (
        hash_text(otp),
        (datetime.now()+timedelta(minutes=5)).isoformat(),
        email
    ))

    conn.commit()
    conn.close()

    send_email(email, "Bank OTP Resend", f"Your OTP is {otp}")

    flash("OTP resent")

    return redirect("/otp")


# ================= CREATE PROFILE =================

@app.route("/create_profile", methods=["GET", "POST"])
def create_profile():

    if request.method == "POST":

        conn = db()

        conn.execute("""
        UPDATE users SET
        full_name=?, phone=?, address=?, aadhaar=?,
        approval_status='pending'
        WHERE email=?
        """, (
            request.form["full_name"],
            request.form["phone"],
            request.form["address"],
            request.form["aadhaar"],
            session["user"]
        ))

        conn.commit()
        conn.close()

        return redirect("/waiting")

    return render_template("create_profile.html")


# ================= WAITING =================

@app.route("/waiting")
def waiting():

    conn = db()

    status = conn.execute("""
    SELECT approval_status FROM users WHERE email=?
    """, (session["user"],)).fetchone()["approval_status"]

    conn.close()

    if status == "approved":
        return redirect("/user_dashboard")

    return render_template("waiting.html")


# ================= USER DASHBOARD =================

@app.route("/user_dashboard")
def user_dashboard():

    conn = db()

    user = conn.execute("""
    SELECT * FROM users WHERE email=?
    """, (session["user"],)).fetchone()

    conn.close()

    return render_template("user_dashboard.html", customer=user)


# ================= ADMIN DASHBOARD =================

@app.route("/admin_dashboard")
@roles_allowed("admin")
def admin_dashboard():

    conn = db()

    users = conn.execute("""
    SELECT id, name, email, role, balance, approval_status
    FROM users
    """).fetchall()

    conn.close()

    return render_template("admin_dashboard.html", users=users)


# ================= APPROVE =================

@app.route("/approve/<int:id>")
@roles_allowed("admin")
def approve(id):

    conn = db()

    conn.execute("""
    UPDATE users SET approval_status='approved'
    WHERE id=?
    """, (id,))

    conn.commit()
    conn.close()

    return redirect("/admin_dashboard")


# ================= LOGOUT =================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/login")


# ================= RUN =================

if __name__ == "__main__":
    app.run(debug=True) 