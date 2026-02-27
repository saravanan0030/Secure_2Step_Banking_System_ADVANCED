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

# ================= DATABASE =================
def db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def hash_text(text):
    return hashlib.sha256(text.encode()).hexdigest()

def generate_account():
    return str(random.randint(1000000000, 9999999999))

def generate_otp():
    return str(random.randint(100000, 999999))

# ================= EMAIL CONFIG =================
SENDER_EMAIL = "securebankindia@gmail.com"
SENDER_PASSWORD = "jxlkyhrlalxnwkpu"

def send_email(to_email, subject, body):
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = SENDER_EMAIL
        msg["To"] = to_email
        server = smtplib.SMTP_SSL("smtp.gmail.com", 465)
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print("Email error:", e)
        return False


def init_db():
    conn = db()
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
            approval_status TEXT DEFAULT 'pending',
            last_login TEXT
        )
    """)

    # OTP TABLE
    c.execute("""
        CREATE TABLE IF NOT EXISTS otp_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT,
            otp TEXT,
            expires_at TEXT,
            attempts INTEGER DEFAULT 0
        )
    """)

    # LOGIN ATTEMPTS TABLE (for password lockout)
    c.execute("""
        CREATE TABLE IF NOT EXISTS login_attempts (
            email TEXT PRIMARY KEY,
            attempts INTEGER DEFAULT 0,
            locked_until TEXT
        )
    """)

    # TRANSACTIONS TABLE
    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            ref TEXT,
            beneficiary_name TEXT,
            account_number TEXT,
            ifsc TEXT,
            type TEXT,
            amount REAL,
            created_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    # DEFAULT ADMIN
    admin = c.execute("SELECT * FROM users WHERE email='admin@bank.com'").fetchone()
    if not admin:
        c.execute("""
            INSERT INTO users (account_number, name, email, password, role, approval_status, last_login)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "0000000000",
            "System Admin",
            "admin@bank.com",
            "admin123",
            "admin",
            "approved",
            datetime.now().isoformat()
        ))

    # DEFAULT EMPLOYEE
    employee = c.execute("SELECT * FROM users WHERE email='employee@bank.com'").fetchone()
    if not employee:
        c.execute("""
            INSERT INTO users (account_number, name, email, password, role, approval_status, last_login)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "1111111111",
            "Bank Employee",
            "employee@bank.com",
            "emp123",
            "employee",
            "approved",
            datetime.now().isoformat()
        ))

    conn.commit()
    conn.close()
# ================= ROLE DECORATOR =================
def roles_allowed(*roles):
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user" not in session:
                flash("Login required")
                return redirect("/login")
            if session.get("role") not in roles:
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
        SELECT role, approval_status, full_name
        FROM users WHERE email=?
    """, (session["user"],)).fetchone()
    conn.close()

    # Admin
    if user["role"] == "admin":
        return redirect("/admin_dashboard")

    # Employee
    if user["role"] == "employee":
        return redirect("/employee_dashboard")

    # User profile not created
    if not user["full_name"]:
        return redirect("/create_profile")

    # Waiting approval
    if user["approval_status"] != "approved":
        return redirect("/waiting")

    # Approved user
    return redirect("/user_dashboard")
# ================= REGISTER =================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        raw_password = request.form["password"]
        password = hash_text(raw_password)
        role = request.form.get("role", "user").lower()

        conn = db()
        # Check if email already exists in final users table
        existing = conn.execute(
            "SELECT id FROM users WHERE email=?", (email,)
        ).fetchone()
        if existing:
            flash("Email already exists")
            conn.close()
            return render_template("register.html")

        # Generate OTP first, and store registration data in session until OTP is verified
        otp = generate_otp()
        expires_at = (datetime.now() + timedelta(minutes=5)).isoformat()

        conn.execute(
            "INSERT INTO otp_codes (email, otp, expires_at) VALUES (?, ?, ?)",
            (email, otp, expires_at),
        )
        conn.commit()
        conn.close()

        # Cache registration details in session until OTP success
        session["pending_registration"] = {
            "name": name,
            "email": email,
            "password": password,
            "role": role,
        }
        session["otp_email"] = email

        send_email(
            email,
            "Your Bank OTP",
            f"Your OTP is {otp}. Expires in 5 minutes. Max 3 attempts.",
        )

        flash("Registration started! OTP sent to your email.")
        return redirect("/verify_otp")

    return render_template("register.html")




 
# ================= OTP VERIFY =================
@app.route("/verify_otp", methods=["GET", "POST"])
def verify_otp():
    if "otp_email" not in session:
        return redirect("/login")

    email = session["otp_email"]
    pending = session.get("pending_registration")

    conn = db()
    record = conn.execute("""
        SELECT * FROM otp_codes WHERE email=?
        ORDER BY id DESC LIMIT 1
    """, (email,)).fetchone()

    if not record:
        session.pop("otp_email")
        return redirect("/login")

    if datetime.fromisoformat(record["expires_at"]) < datetime.now():
        session.pop("otp_email")
        return redirect("/login")

    if request.method == "POST":
        otp_input = request.form["otp"]

        if record["attempts"] >= 3:
            session.pop("otp_email")
            flash("Too many incorrect attempts. Please register again.")
            return redirect("/login")

        if otp_input != record["otp"]:
            conn.execute(
                "UPDATE otp_codes SET attempts=attempts+1 WHERE id=?",
                (record["id"],),
            )
            conn.commit()
            conn.close()
            flash("Incorrect OTP.")
            return redirect("/verify_otp")

        # OTP is correct. If this is a fresh registration, create the user now.
        if pending and pending.get("email") == email:
            acc = generate_account()  
            try:
                conn.execute(
                    """
                    INSERT INTO users (account_number, name, email, password, role, approval_status)
                    VALUES (?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        acc,
                        pending["name"],
                        pending["email"],
                        pending["password"],
                        pending["role"],
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                # If a race created the user already, ignore and continue
                conn.rollback()

        # Log user in and move to profile creation
        session["user"] = email
        conn.execute(
            "UPDATE users SET last_login=? WHERE email=?",
            (datetime.now().isoformat(), email),
        )
        conn.commit()
        conn.close()

        # Clear OTP and pending registration cache
        session.pop("otp_email", None)
        session.pop("pending_registration", None)

        return redirect("/create_profile")

    remaining_attempts = max(0, 3 - (record["attempts"] or 0))
    return render_template(
        "otp.html",
        expires_at=record["expires_at"],
        remaining_attempts=remaining_attempts,
    )



# ================= RESEND OTP =================
@app.route("/resend_otp")
def resend_otp():
    if "otp_email" not in session:
        flash("No OTP process found. Please register again.")
        return redirect("/login")

    email = session["otp_email"]

    otp = generate_otp()
    expires_at = (datetime.now() + timedelta(minutes=5)).isoformat()

    conn = db()

    # Optional: delete old OTPs for this email (clean system)
    conn.execute("DELETE FROM otp_codes WHERE email=?", (email,))

    conn.execute("""
        INSERT INTO otp_codes (email, otp, expires_at, attempts)
        VALUES (?, ?, ?, 0)
    """, (email, otp, expires_at))

    conn.commit()
    conn.close()

    send_email(
        email,
        "Your Bank OTP (Resent)",
        f"Your new OTP is {otp}. It expires in 5 minutes. Maximum 3 attempts allowed."
    )

    flash("New OTP sent to your email.")
    return redirect("/verify_otp")

 
 # ================= LOGIN =================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        raw_password = request.form["password"]
        password = hash_text(raw_password)
        selected_role = request.form.get("role", "").lower()

        conn = db()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

        # Check lock status (per email)
        la = conn.execute(
            "SELECT attempts, locked_until FROM login_attempts WHERE email=?",
            (email,),
        ).fetchone()

        if la and la["locked_until"]:
            try:
                locked_until = datetime.fromisoformat(la["locked_until"])
            except ValueError:
                locked_until = None
            if locked_until and locked_until > datetime.now():
                remaining = locked_until - datetime.now()
                minutes = int(remaining.total_seconds() // 60) + 1
                flash(f"Account locked due to repeated failures. Try again in about {minutes} minute(s).")
                conn.close()
                return redirect("/login")

        if not user:
            flash("User not found")
            conn.close()
            return redirect("/login")

        stored_pw = user["password"]
        # Support both hashed and legacy plain-text passwords (for default admin/employee)
        if stored_pw != password and stored_pw != raw_password:
            # Increment login attempts
            if la:
                attempts = (la["attempts"] or 0) + 1
                locked_until_val = la["locked_until"]
            else:
                attempts = 1
                locked_until_val = None

            if attempts >= 3:
                locked_until_val = (datetime.now() + timedelta(minutes=15)).isoformat()
                conn.execute(
                    """
                    INSERT INTO login_attempts (email, attempts, locked_until)
                    VALUES (?, ?, ?)
                    ON CONFLICT(email) DO UPDATE SET attempts=?, locked_until=?
                    """,
                    (email, attempts, locked_until_val, attempts, locked_until_val),
                )
                conn.commit()
                conn.close()
                flash("Too many invalid password attempts. Account locked for 15 minutes.")
                return redirect("/login")
            else:
                conn.execute(
                    """
                    INSERT INTO login_attempts (email, attempts, locked_until)
                    VALUES (?, ?, NULL)
                    ON CONFLICT(email) DO UPDATE SET attempts=?, locked_until=NULL
                    """,
                    (email, attempts, attempts),
                )
                conn.commit()
                conn.close()
                flash(f"Invalid password. {3 - attempts} attempt(s) remaining before lock.")
                return redirect("/login")

        # Successful login: reset attempts
        conn.execute(
            "DELETE FROM login_attempts WHERE email=?",
            (email,),
        )
        conn.commit()
        conn.close()

        db_role = user["role"].lower()

        # Convert old 'customer' role to 'user'
        if db_role == "customer":
            db_role = "user"

        if db_role != selected_role:
            flash(f"This account is registered as '{user['role']}'")
            return redirect("/login")

        if db_role == "user" and user["approval_status"] != "approved":
            flash("Account not approved yet")
            return redirect("/login")

        session.clear()
        session["user"] = email
        session["role"] = db_role

        flash(f"Login successful as {db_role.capitalize()}")

        if db_role == "admin":
            return redirect("/admin_dashboard")
        elif db_role == "employee":
            return redirect("/employee_dashboard")
        else:
            return redirect("/user_dashboard")

    return render_template("login.html")



# ================= CREATE PROFILE =================
@app.route("/create_profile", methods=["GET", "POST"])
def create_profile():

    if "user" not in session:
        flash("Login required")
        return redirect("/login")

    if request.method == "POST":

        full_name = request.form.get("full_name")
        phone = request.form.get("phone")
        address = request.form.get("address")
        aadhaar = request.form.get("aadhaar")

        conn = db()
        conn.execute("""
            UPDATE users
            SET full_name=?, phone=?, address=?, aadhaar=?, approval_status='pending'
            WHERE email=?
        """, (full_name, phone, address, aadhaar, session["user"]))

        conn.commit()
        conn.close()

        flash("Profile submitted for approval.")
        return redirect("/waiting")

    return render_template("create_profile.html")
 # ================= WAITING =================
@app.route("/waiting")
def waiting():
    if "user" not in session:
        return redirect("/login")

    conn = db()
    status = conn.execute(
        "SELECT approval_status FROM users WHERE email=?",
        (session["user"],)
    ).fetchone()["approval_status"]
    conn.close()

    if status == "approved":
        flash("Account approved! Welcome.")
        return redirect("/user_dashboard")

    return render_template("waiting.html")

# ================= DASHBOARDS =================
@app.route("/user_dashboard")
@roles_allowed("user")
def user_dashboard():
    conn = db()
    user = conn.execute(
        "SELECT * FROM users WHERE email=?",
        (session["user"],)
    ).fetchone()

    transactions = conn.execute(
        """
        SELECT * FROM transactions
        WHERE user_id=?
        ORDER BY datetime(created_at) DESC
        LIMIT 50
        """,
        (user["id"],),
    ).fetchall()

    conn.close()
    return render_template("user_dashboard.html", customer=user, transactions=transactions)


@app.route("/user_transaction", methods=["POST"])
@roles_allowed("user")
def user_transaction():
    amount_raw = request.form.get("amount", "").strip()
    tx_type = request.form.get("type", "imps").lower()
    beneficiary_name = request.form.get("beneficiary_name", "").strip()
    account_number = request.form.get("account_number", "").strip()
    ifsc = request.form.get("ifsc", "").strip()

    if not amount_raw:
        flash("Please enter amount.")
        return redirect("/user_dashboard")

    try:
        amount = float(amount_raw)
    except ValueError:
        flash("Invalid amount.")
        return redirect("/user_dashboard")

    if amount <= 0:
        flash("Amount must be greater than zero.")
        return redirect("/user_dashboard")

    conn = db()
    user = conn.execute(
        "SELECT * FROM users WHERE email=?",
        (session["user"],)
    ).fetchone()

    if not user:
        conn.close()
        flash("User not found.")
        return redirect("/login")

    current_balance = user["balance"] or 0
    ref = f"TXN{random.randint(100000, 999999)}"
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        """
        INSERT INTO transactions
            (user_id, ref, beneficiary_name, account_number, ifsc, type, amount, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user["id"], ref, beneficiary_name, account_number, ifsc, tx_type, amount, created_at),
    )

    new_balance = current_balance - amount
    conn.execute(
        "UPDATE users SET balance=? WHERE id=?",
        (new_balance, user["id"]),
    )

    conn.commit()
    conn.close()

    flash("Transfer successful.")
    return redirect("/user_dashboard")


@app.route("/employee_dashboard")
@roles_allowed("employee")
def employee_dashboard():
    conn = db()
    employee = conn.execute(
        "SELECT * FROM users WHERE email=?",
        (session["user"],)
    ).fetchone()
    # Show both legacy 'customer' and new 'user' roles
    users = conn.execute(
        "SELECT * FROM users WHERE role IN ('user','customer')"
    ).fetchall()

    total_users = len(users)
    approved_users = sum(1 for u in users if u["approval_status"] == "approved")
    pending_users = sum(1 for u in users if u["approval_status"] != "approved")
    total_balance = sum((u["balance"] or 0) for u in users)

    conn.close()
    return render_template(
        "employee_dashboard.html",
        employee=employee,
        users=users,
        total_users=total_users,
        approved_users=approved_users,
        pending_users=pending_users,
        total_balance=total_balance,
    )


@app.route("/employee_user/<int:user_id>", methods=["GET", "POST"])
@roles_allowed("employee")
def employee_user(user_id):
    conn = db()
    user = conn.execute(
        "SELECT * FROM users WHERE id=?",
        (user_id,),
    ).fetchone()

    if not user:
        conn.close()
        flash("Customer not found.")
        return redirect("/employee_dashboard")

    if request.method == "POST":
        full_name = request.form.get("full_name") or None
        phone = request.form.get("phone") or None
        address = request.form.get("address") or None
        aadhaar = request.form.get("aadhaar") or None
        approval_status = request.form.get("approval_status") or user["approval_status"]

        balance_raw = request.form.get("balance", "").strip()
        try:
            balance = float(balance_raw) if balance_raw else user["balance"]
        except ValueError:
            balance = user["balance"]

        conn.execute(
            """
            UPDATE users
            SET full_name=?, phone=?, address=?, aadhaar=?, balance=?, approval_status=?
            WHERE id=?
            """,
            (full_name, phone, address, aadhaar, balance, approval_status, user_id),
        )
        conn.commit()
        conn.close()
        flash("Customer profile updated.")
        return redirect("/employee_dashboard")

    conn.close()
    return render_template("employee_user.html", user=user)

@app.route("/admin_dashboard")
@roles_allowed("admin")
def admin_dashboard():
    conn = db()
    users = conn.execute("SELECT * FROM users").fetchall()

    total_users = len(users)
    total_admins = sum(1 for u in users if u["role"] == "admin")
    total_employees = sum(1 for u in users if u["role"] == "employee")
    total_customers = sum(1 for u in users if u["role"] not in ("admin", "employee"))
    pending_users = sum(1 for u in users if u["approval_status"] != "approved")
    approved_users = sum(1 for u in users if u["approval_status"] == "approved")
    total_balance = sum((u["balance"] or 0) for u in users)

    conn.close()
    return render_template(
        "admin_dashboard.html",
        users=users,
        total_users=total_users,
        total_admins=total_admins,
        total_employees=total_employees,
        total_customers=total_customers,
        pending_users=pending_users,
        approved_users=approved_users,
        total_balance=total_balance,
    )

@app.route("/approve/<int:id>")
@roles_allowed("admin")
def approve(id):
    conn = db()
    conn.execute("UPDATE users SET approval_status='approved' WHERE id=?", (id,))
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
    init_db()
    app.run(debug=True)