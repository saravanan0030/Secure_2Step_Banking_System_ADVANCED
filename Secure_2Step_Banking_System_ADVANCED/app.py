from flask import Flask, render_template, request, redirect, session, flash
import sqlite3
import random
import hashlib
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = "super_secret_key_123"

DB_NAME = "database.db"

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
        last_login TEXT
    )
    """)
    # Create Admin
    admin_email = "admin@bank.com"
    admin_pw = hashlib.sha256("admin123".encode()).hexdigest()
    admin = c.execute("SELECT * FROM users WHERE email=?", (admin_email,)).fetchone()
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
            datetime.now().isoformat()
        ))
    conn.commit()
    conn.close()

init_db()

# ================= UTILITIES =================

def hash_text(text):
    return hashlib.sha256(text.encode()).hexdigest()

def generate_account():
    return str(random.randint(1000000000, 9999999999))

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
    FROM users WHERE email=?""", (session["user"],)).fetchone()
    conn.close()
    if user["role"] == "admin":
        return redirect("/admin_dashboard")
    if user["role"] == "employee":
        return redirect("/employee_dashboard")
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
            VALUES (?,?,?,?,?)""", (
                acc, name, email, password, None
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
        selected_role = request.form["role"]
        conn = db()
        user = conn.execute("""
        SELECT email,password,role
        FROM users WHERE email=?""", (email,)).fetchone()
        conn.close()

        if not user:
            flash("User not found")
            return redirect("/login")
        if password != user["password"]:
            flash("Invalid password")
            return redirect("/login")
        if user["role"] != selected_role:
            flash(f"Invalid role selected for this account ({user['role']})")
            return redirect("/login")

        session.clear()
        session["user"] = email
        session["role"] = user["role"]
        flash("Login success")

        if user["role"] == "admin":
            return redirect("/admin_dashboard")
        elif user["role"] == "employee":
            return redirect("/employee_dashboard")
        else:
            return redirect("/user_dashboard")
    return render_template("login.html")

# ================= CREATE PROFILE =================

@app.route("/create_profile", methods=["GET", "POST"])
def create_profile():
    if request.method == "POST":
        conn = db()
        conn.execute("""UPDATE users SET full_name=?, phone=?, address=?, aadhaar=?,
                        approval_status='pending' WHERE email=?""",
                     (request.form["full_name"], request.form["phone"],
                      request.form["address"], request.form["aadhaar"], session["user"]))
        conn.commit()
        conn.close()
        return redirect("/waiting")
    return render_template("create_profile.html")

# ================= WAITING =================

@app.route("/waiting")
def waiting():
    conn = db()
    status = conn.execute("""SELECT approval_status FROM users WHERE email=?""",
                          (session["user"],)).fetchone()["approval_status"]
    conn.close()
    if status == "approved":
        return redirect("/user_dashboard")
    return render_template("waiting.html")

# ================= USER DASHBOARD =================

@app.route("/user_dashboard")
def user_dashboard():
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE email=?", (session["user"],)).fetchone()
    conn.close()
    return render_template("user_dashboard.html", customer=user)

# ================= EMPLOYEE MODULE =================

@app.route("/employee_dashboard")
@roles_allowed("employee")
def employee_dashboard():
    conn = db()
    employee = conn.execute("SELECT * FROM users WHERE email=?", (session["user"],)).fetchone()
    users = conn.execute("""
        SELECT id, account_number, name, email, full_name, phone, address, aadhaar, approval_status
        FROM users WHERE role='user'
    """).fetchall()
    conn.close()
    return render_template("employee_dashboard.html", employee=employee, users=users)


@app.route("/employee_user/<int:user_id>", methods=["GET", "POST"])
@roles_allowed("employee")
def employee_user_profile(user_id):
    conn = db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if request.method == "POST":
        full_name = request.form["full_name"]
        phone = request.form["phone"]
        address = request.form["address"]
        aadhaar = request.form["aadhaar"]
        approval_status = request.form["approval_status"]
        conn.execute("""
            UPDATE users SET full_name=?, phone=?, address=?, aadhaar=?, approval_status=?
            WHERE id=?
        """, (full_name, phone, address, aadhaar, approval_status, user_id))
        conn.commit()
        conn.close()
        flash("User profile updated successfully")
        return redirect("/employee_dashboard")
    conn.close()
    return render_template("employee_user_profile.html", employee=session["user"], user=user)


@app.route("/create_employee", methods=["POST"])
@roles_allowed("employee", "admin")
def create_employee():
    name = request.form["name"]
    email = request.form["email"]
    password = hash_text(request.form["password"])
    role = request.form.get("role", "employee")
    conn = db()
    try:
        conn.execute("""
        INSERT INTO users (name, email, password, role, last_login)
        VALUES (?,?,?,?,?)""", (name, email, password, role, None))
        conn.commit()
        flash("Employee created successfully")
    except sqlite3.IntegrityError:
        flash("Email already exists")
    conn.close()
    return redirect("/employee_dashboard")

# ================= ADMIN DASHBOARD =================

@app.route("/admin_dashboard")
@roles_allowed("admin")
def admin_dashboard():
    conn = db()
    users = conn.execute("SELECT id, name, email, role, balance, approval_status FROM users").fetchall()
    conn.close()
    return render_template("admin_dashboard.html", users=users)


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
    app.run(debug=True) 