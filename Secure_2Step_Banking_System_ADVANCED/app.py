from flask import Flask, render_template, request, redirect, session, flash, url_for
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


# =====================================================
# DATABASE CONNECTION
# =====================================================

def db():
    return sqlite3.connect(DB_NAME)


# =====================================================
# DATABASE INITIALIZATION
# =====================================================

def init_db():

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # USERS TABLE
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

        is_locked INTEGER DEFAULT 0,
        lock_time TEXT,
        failed_attempts INTEGER DEFAULT 0,

        otp_hash TEXT,
        otp_expiry TEXT,

        last_login TEXT
    )
    """)

    # TRANSACTIONS TABLE
    c.execute("""
    CREATE TABLE IF NOT EXISTS transactions (

        id INTEGER PRIMARY KEY AUTOINCREMENT,

        sender_acc TEXT,
        amount REAL,
        type TEXT,
        performed_by TEXT,

        timestamp TEXT
    )
    """)

    # CREATE DEFAULT ADMIN
    admin_email = "admin@bank.com"
    admin_pw = hashlib.sha256("admin123".encode()).hexdigest()

    user = c.execute("SELECT * FROM users WHERE email=?",
                     (admin_email,)).fetchone()

    if not user:

        c.execute("""
        INSERT INTO users
        (account_number,name,email,password,role)
        VALUES (?,?,?,?,?)
        """, (
            "0000000000",
            "System Admin",
            admin_email,
            admin_pw,
            "admin"
        ))

        print("Admin created")

    conn.commit()
    conn.close()


# Run database init
init_db()


# =====================================================
# UTILITIES
# =====================================================

def hash_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def generate_account():
    return str(random.randint(1000000000, 9999999999))


def generate_otp():
    return str(random.randint(100000, 999999))


# =====================================================
# ROLE SECURITY
# =====================================================

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


# =====================================================
# EMAIL CONFIG
# =====================================================

SENDER_EMAIL = "k.saravanan0030@gmail.com"
SENDER_PASSWORD = "hrgdsfafefqynnvo"


def send_email(to, subject, body):

    try:

        msg = MIMEText(body)

        msg["Subject"] = subject
        msg["From"] = SENDER_EMAIL
        msg["To"] = to

        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)

        server.login(SENDER_EMAIL, SENDER_PASSWORD)

        server.sendmail(SENDER_EMAIL, to, msg.as_string())

        server.quit()

        return True

    except Exception as e:

        print("EMAIL ERROR:", e)
        return False


# =====================================================
# HOME
# =====================================================

@app.route("/")
def home():

    if "user" not in session:
        return redirect("/login")

    role = session["role"]

    if role == "admin":
        return redirect("/admin_dashboard")

    if role == "employee":
        return redirect("/employee_dashboard")

    conn = db()

    profile = conn.execute("""
        SELECT full_name FROM users WHERE email=?
    """, (session["user"],)).fetchone()

    conn.close()

    if profile and profile[0]:
        return redirect("/user_dashboard")

    return redirect("/create_profile") 

# =====================================================
# REGISTER
# =====================================================

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
            (account_number,name,email,password)
            VALUES (?,?,?,?)
            """, (acc, name, email, password))

            conn.commit()

            flash("Registration successful")

            return redirect("/login")

        except:

            flash("Email already exists")

        conn.close()

    return render_template("register.html")


# =====================================================
# LOGIN
# =====================================================
 # ================= LOGIN =================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = hash_text(request.form["password"])

        conn = db()
        user = conn.execute("""
        SELECT password,is_locked,lock_time,failed_attempts,last_login,role
        FROM users WHERE email=?
        """, (email,)).fetchone()

        if not user:
            flash("User not found")
            conn.close()
            return redirect("/login")

        db_pw, locked, lock_time, attempts, last_login, role = user

        # CHECK LOCK
        if locked == 1 and lock_time:
            unlock_time = datetime.fromisoformat(lock_time) + timedelta(minutes=5)
            if datetime.now() < unlock_time:
                flash("Account locked. Try after 5 minutes")
                conn.close()
                return redirect("/login")

        # CORRECT PASSWORD
        if password == db_pw:
            # Direct login if already verified before
            if last_login:
                session["user"] = email
                session["role"] = role
                conn.execute("UPDATE users SET last_login=? WHERE email=?",
                             (datetime.now().isoformat(), email))
                conn.commit()
                conn.close()
                flash("Login successful")
                return redirect("/user_dashboard")
            else:
                # First-time login → OTP
                otp = generate_otp()
                conn.execute("""
                UPDATE users SET
                    otp_hash=?,
                    otp_expiry=?,
                    failed_attempts=0,
                    is_locked=0
                WHERE email=?
                """, (hash_text(otp),
                      (datetime.now()+timedelta(minutes=2)).isoformat(),
                      email))
                conn.commit()
                conn.close()
                send_email(email, "Bank OTP", f"Your OTP is {otp}")
                session["temp_user"] = email
                flash("OTP sent. Please verify.")
                return redirect("/otp")

        # WRONG PASSWORD
        else:
            attempts = (attempts or 0) + 1
            if attempts >= 3:
                conn.execute("""
                UPDATE users SET is_locked=1, lock_time=? WHERE email=?
                """, (datetime.now().isoformat(), email))
                flash("Account locked for 5 minutes")
            else:
                conn.execute("""
                UPDATE users SET failed_attempts=? WHERE email=?
                """, (attempts, email))
                flash(f"Invalid password Attempt {attempts}/3")
            conn.commit()
            conn.close()
            return redirect("/login")
    return render_template("login.html")

# =====================================================
# OTP VERIFY
# =====================================================

@app.route("/otp", methods=["GET", "POST"])
def otp():

    if "temp_user" not in session:
        return redirect("/login")

    email = session["temp_user"]

    if request.method == "POST":

        entered = hash_text(request.form["otp"])

        conn = db()

        user = conn.execute("""
        SELECT otp_hash,otp_expiry,role
        FROM users WHERE email=?
        """, (email,)).fetchone()

        if user:

            db_hash, expiry, role = user

            if expiry and datetime.now() > datetime.fromisoformat(expiry):

                flash("OTP expired")
                return redirect("/otp")

            if entered == db_hash:

                session.clear()

                session["user"] = email
                session["role"] = role

                conn.execute("""
                UPDATE users SET

                otp_hash=NULL,
                otp_expiry=NULL,
                last_login=?

                WHERE email=?
                """, (datetime.now().isoformat(), email))

                conn.commit()
                conn.close()

                flash("Login success")

                return redirect("/")

        conn.close()

        flash("Invalid OTP")

    return render_template("otp.html")


# =====================================================
# RESEND OTP
# =====================================================

@app.route("/resend_otp")
def resend_otp():

    if "temp_user" not in session:
        return redirect("/login")

    email = session["temp_user"]

    otp = generate_otp()

    conn = db()

    conn.execute("""
    UPDATE users SET

    otp_hash=?,
    otp_expiry=?

    WHERE email=?
    """, (

        hash_text(otp),
        (datetime.now() +
         timedelta(minutes=2)).isoformat(),
        email
    ))

    conn.commit()
    conn.close()

    send_email(email, "Resend OTP", f"Your OTP is {otp}")

    flash("New OTP sent")

    return redirect("/otp")


# =====================================================
# ADMIN DASHBOARD
# =====================================================

@app.route("/admin_dashboard")
@roles_allowed("admin")
def admin_dashboard():

    conn = db()

    users = conn.execute("""
    SELECT name,email,role,balance
    FROM users
    """).fetchall()

    logs = conn.execute("""
    SELECT *
    FROM transactions
    ORDER BY id DESC
    """).fetchall()

    conn.close()

    return render_template("admin_dashboard.html",
                           users=users,
                           logs=logs)


# =====================================================
# EMPLOYEE DASHBOARD
# =====================================================

@app.route("/employee_dashboard")
@roles_allowed("employee", "admin")
def employee_dashboard():

    conn = db()

    users = conn.execute("""
    SELECT name,account_number,balance
    FROM users
    """).fetchall()

    conn.close()

    return render_template("employee_dashboard.html",
                           users=users)


# =====================================================
# CREATE PROFILE
# =====================================================
@app.route("/create_profile", methods=["GET","POST"])
def create_profile():

    if "user" not in session:
        return redirect("/login")

    email = session["user"]

    conn = db()

    # CHECK IF PROFILE EXISTS
    existing = conn.execute("""
        SELECT full_name FROM users WHERE email=?
    """, (email,)).fetchone()

    # IF PROFILE EXISTS → GO DASHBOARD
    if existing and existing[0]:
        conn.close()
        return redirect("/user_dashboard")

    if request.method == "POST":

        full_name = request.form["full_name"]
        phone = request.form["phone"]
        address = request.form["address"]
        aadhaar = request.form["aadhaar"]

        conn.execute("""
            UPDATE users SET
            full_name=?,
            phone=?,
            address=?,
            aadhaar=?
            WHERE email=?
        """, (full_name, phone, address, aadhaar, email))

        conn.commit()
        conn.close()

        flash("Profile Created Successfully")

        return redirect("/user_dashboard")

    conn.close()

    return render_template("create_profile.html") 



@app.route("/user_dashboard")
def user_dashboard():
    if "user" not in session:
        return redirect("/login")
    
    email = session["user"]
    conn = db()
    customer = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    conn.close()

    if not customer:
        flash("User not found")
        return redirect("/login")

    # Pass 'customer' to template
    return render_template("user_dashboard.html", customer=customer)











# =====================================================
# RUN
# =====================================================

if __name__ == "__main__":
    app.run(debug=True) 