# Multi-User Authentication Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform single-user local app into multi-user web app with email/password authentication and per-user data isolation.

**Architecture:** Add Flask-Login for session management, bcrypt for password hashing. Add `user_id` column to all existing tables and filter all queries by current user. User's email becomes their reminder address automatically.

**Tech Stack:** Flask-Login, Flask-WTF, bcrypt, SQLite (PostgreSQL later for production)

---

## Task 1: Add Dependencies

**Files:**
- Modify: `requirements.txt`

**Step 1: Add new dependencies to requirements.txt**

Add these lines to `requirements.txt`:

```
flask-login
flask-wtf
bcrypt
```

**Step 2: Install dependencies**

Run: `pip3 install -r requirements.txt`
Expected: Successfully installed flask-login, flask-wtf, bcrypt

**Step 3: Verify installation**

Run: `python3 -c "import flask_login; import flask_wtf; import bcrypt; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add requirements.txt
git commit -m "Add auth dependencies: flask-login, flask-wtf, bcrypt"
```

---

## Task 2: Add User Model

**Files:**
- Modify: `models.py`
- Create: `tests/test_models.py`

**Step 1: Write failing test for User model**

Create `tests/test_models.py`:

```python
"""Tests for data models."""

import pytest
from models import User


def test_user_creation():
    """Test basic User creation."""
    user = User(
        id=1,
        email="test@example.com",
        password_hash="hashed",
        name="Test User"
    )
    assert user.email == "test@example.com"
    assert user.name == "Test User"
    assert user.is_active == True


def test_user_flask_login_interface():
    """Test User implements Flask-Login interface."""
    user = User(id=1, email="test@example.com", password_hash="x", name="Test")

    # Flask-Login requires these
    assert user.is_authenticated == True
    assert user.is_active == True
    assert user.is_anonymous == False
    assert user.get_id() == "1"
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_models.py -v`
Expected: FAIL with "cannot import name 'User' from 'models'"

**Step 3: Add User model to models.py**

Add after the `ServedDocument` class (around line 243):

```python
@dataclass
class User:
    """A user account."""
    id: Optional[int] = None
    email: str = ""
    password_hash: str = ""
    name: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    is_active: bool = True

    # Flask-Login interface
    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def is_anonymous(self) -> bool:
        return False

    def get_id(self) -> str:
        return str(self.id)
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_models.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add models.py tests/test_models.py
git commit -m "Add User model with Flask-Login interface"
```

---

## Task 3: Add Users Table to Database

**Files:**
- Modify: `database.py`
- Create: `tests/test_database_users.py`

**Step 1: Write failing test for user database operations**

Create `tests/test_database_users.py`:

```python
"""Tests for user database operations."""

import pytest
from pathlib import Path
import tempfile

from database import Database
from models import User


@pytest.fixture
def db():
    """Create a test database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        database = Database(db_path)
        database.initialize()
        yield database


def test_create_user(db):
    """Test creating a user."""
    user = User(email="test@example.com", password_hash="hashed123", name="Test User")
    user_id = db.create_user(user)
    assert user_id == 1


def test_get_user_by_email(db):
    """Test finding user by email."""
    user = User(email="test@example.com", password_hash="hashed123", name="Test User")
    db.create_user(user)

    found = db.get_user_by_email("test@example.com")
    assert found is not None
    assert found.email == "test@example.com"
    assert found.name == "Test User"


def test_get_user_by_email_not_found(db):
    """Test finding non-existent user returns None."""
    found = db.get_user_by_email("nobody@example.com")
    assert found is None


def test_get_user_by_id(db):
    """Test finding user by ID."""
    user = User(email="test@example.com", password_hash="hashed123", name="Test User")
    user_id = db.create_user(user)

    found = db.get_user(user_id)
    assert found is not None
    assert found.id == user_id
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_database_users.py -v`
Expected: FAIL with "no such table: users" or "has no attribute 'create_user'"

**Step 3: Add users table to SCHEMA in database.py**

Add after the served_documents table definition (around line 105):

```sql
-- Users table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Step 4: Add User import to database.py**

Update the imports at top of `database.py` to include User:

```python
from models import (
    Certificate,
    CertificateType,
    ComplianceEvent,
    EventPriority,
    EventStatus,
    Property,
    PropertyType,
    RentFrequency,
    RequiredDocument,
    ServedDocument,
    Tenancy,
    User,
)
```

**Step 5: Add user CRUD methods to Database class**

Add these methods to the `Database` class (at the end, before the class closes):

```python
    # User operations
    def create_user(self, user: User) -> int:
        """Create a new user and return their ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                """INSERT INTO users (email, password_hash, name, is_active)
                   VALUES (?, ?, ?, ?)""",
                (user.email, user.password_hash, user.name, user.is_active),
            )
            return cursor.lastrowid

    def get_user(self, user_id: int) -> Optional[User]:
        """Get a user by ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            )
            row = cursor.fetchone()
            if row:
                return User(
                    id=row["id"],
                    email=row["email"],
                    password_hash=row["password_hash"],
                    name=row["name"],
                    is_active=bool(row["is_active"]),
                    created_at=row["created_at"],
                )
            return None

    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get a user by email address."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            )
            row = cursor.fetchone()
            if row:
                return User(
                    id=row["id"],
                    email=row["email"],
                    password_hash=row["password_hash"],
                    name=row["name"],
                    is_active=bool(row["is_active"]),
                    created_at=row["created_at"],
                )
            return None
```

**Step 6: Run test to verify it passes**

Run: `python3 -m pytest tests/test_database_users.py -v`
Expected: PASS (4 tests)

**Step 7: Commit**

```bash
git add database.py tests/test_database_users.py
git commit -m "Add users table and CRUD operations"
```

---

## Task 4: Add Password Hashing Utility

**Files:**
- Create: `services/auth.py`
- Create: `tests/test_auth.py`

**Step 1: Write failing test for password hashing**

Create `tests/test_auth.py`:

```python
"""Tests for authentication utilities."""

import pytest
from services.auth import hash_password, check_password


def test_hash_password_returns_string():
    """Test that hash_password returns a string."""
    hashed = hash_password("mypassword")
    assert isinstance(hashed, str)
    assert len(hashed) > 0


def test_hash_password_different_each_time():
    """Test that same password produces different hashes (salted)."""
    hash1 = hash_password("mypassword")
    hash2 = hash_password("mypassword")
    assert hash1 != hash2


def test_check_password_correct():
    """Test that correct password validates."""
    hashed = hash_password("mypassword")
    assert check_password("mypassword", hashed) == True


def test_check_password_incorrect():
    """Test that wrong password fails."""
    hashed = hash_password("mypassword")
    assert check_password("wrongpassword", hashed) == False
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_auth.py -v`
Expected: FAIL with "No module named 'services.auth'"

**Step 3: Create services/auth.py**

Create `services/auth.py`:

```python
"""Authentication utilities."""

import bcrypt


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def check_password(password: str, password_hash: str) -> bool:
    """Check if a password matches a hash."""
    return bcrypt.checkpw(
        password.encode("utf-8"),
        password_hash.encode("utf-8")
    )
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_auth.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add services/auth.py tests/test_auth.py
git commit -m "Add password hashing utilities with bcrypt"
```

---

## Task 5: Add Login and Register Templates

**Files:**
- Create: `templates/login.html`
- Create: `templates/register.html`

**Step 1: Create login.html**

Create `templates/login.html`:

```html
{% extends "base.html" %}

{% block title %}Login - Landlord Command Centre{% endblock %}

{% block content %}
<div style="max-width: 400px; margin: 2rem auto;">
    <h1>Login</h1>

    <form method="POST">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

        <div class="form-group">
            <label for="email">Email</label>
            <input type="email" id="email" name="email" required autofocus>
        </div>

        <div class="form-group">
            <label for="password">Password</label>
            <input type="password" id="password" name="password" required>
        </div>

        <button type="submit" class="btn btn-success" style="width: 100%;">Login</button>
    </form>

    <p style="margin-top: 1rem; text-align: center;">
        Don't have an account? <a href="{{ url_for('register') }}">Register</a>
    </p>

    <p style="text-align: center;">
        <a href="{{ url_for('forgot_password') }}">Forgot password?</a>
    </p>
</div>
{% endblock %}
```

**Step 2: Create register.html**

Create `templates/register.html`:

```html
{% extends "base.html" %}

{% block title %}Register - Landlord Command Centre{% endblock %}

{% block content %}
<div style="max-width: 400px; margin: 2rem auto;">
    <h1>Register</h1>

    <form method="POST">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

        <div class="form-group">
            <label for="name">Your name</label>
            <input type="text" id="name" name="name" required autofocus>
        </div>

        <div class="form-group">
            <label for="email">Email</label>
            <input type="email" id="email" name="email" required>
        </div>

        <div class="form-group">
            <label for="password">Password</label>
            <input type="password" id="password" name="password" required minlength="8">
            <small style="color: #666;">At least 8 characters</small>
        </div>

        <div class="form-group">
            <label for="password_confirm">Confirm password</label>
            <input type="password" id="password_confirm" name="password_confirm" required>
        </div>

        <button type="submit" class="btn btn-success" style="width: 100%;">Register</button>
    </form>

    <p style="margin-top: 1rem; text-align: center;">
        Already have an account? <a href="{{ url_for('login') }}">Login</a>
    </p>
</div>
{% endblock %}
```

**Step 3: Commit**

```bash
git add templates/login.html templates/register.html
git commit -m "Add login and register templates"
```

---

## Task 6: Add Authentication Routes

**Files:**
- Modify: `app.py`

**Step 1: Add Flask-Login setup to app.py**

Add these imports at the top of `app.py` (after existing imports):

```python
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from services.auth import hash_password, check_password
from models import User
```

Add after `app.secret_key = ...` line:

```python
# CSRF protection
csrf = CSRFProtect(app)

# Login manager setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."


@login_manager.user_loader
def load_user(user_id: str):
    """Load user by ID for Flask-Login."""
    db = get_db()
    return db.get_user(int(user_id))
```

**Step 2: Add login route**

Add after the `load_user` function:

```python
@app.route("/login", methods=["GET", "POST"])
def login():
    """Login page."""
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        db = get_db()
        user = db.get_user_by_email(email)

        if user and check_password(password, user.password_hash):
            login_user(user, remember=True)
            flash(f"Welcome back, {user.name}!", "success")
            next_page = request.args.get("next")
            return redirect(next_page or url_for("index"))
        else:
            flash("Invalid email or password", "error")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Registration page."""
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        # Validation
        if not name or not email or not password:
            flash("All fields are required", "error")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must be at least 8 characters", "error")
            return render_template("register.html")

        if password != password_confirm:
            flash("Passwords do not match", "error")
            return render_template("register.html")

        db = get_db()

        # Check if email already exists
        if db.get_user_by_email(email):
            flash("An account with this email already exists", "error")
            return render_template("register.html")

        # Create user
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=name,
        )
        user_id = db.create_user(user)
        user.id = user_id

        login_user(user, remember=True)
        flash(f"Welcome, {name}! Your account has been created.", "success")
        return redirect(url_for("index"))

    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    """Logout the current user."""
    logout_user()
    flash("You have been logged out", "success")
    return redirect(url_for("login"))
```

**Step 3: Add placeholder routes for forgot password**

Add after logout route:

```python
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Request password reset."""
    if request.method == "POST":
        flash("If that email exists, a reset link has been sent.", "success")
        return redirect(url_for("login"))
    return render_template("forgot_password.html")
```

**Step 4: Create forgot_password.html**

Create `templates/forgot_password.html`:

```html
{% extends "base.html" %}

{% block title %}Forgot Password - Landlord Command Centre{% endblock %}

{% block content %}
<div style="max-width: 400px; margin: 2rem auto;">
    <h1>Forgot Password</h1>
    <p style="color: #666;">Enter your email and we'll send you a reset link.</p>

    <form method="POST">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

        <div class="form-group">
            <label for="email">Email</label>
            <input type="email" id="email" name="email" required autofocus>
        </div>

        <button type="submit" class="btn btn-success" style="width: 100%;">Send Reset Link</button>
    </form>

    <p style="margin-top: 1rem; text-align: center;">
        <a href="{{ url_for('login') }}">Back to login</a>
    </p>
</div>
{% endblock %}
```

**Step 5: Test manually**

Run: `python3 app.py`
Visit: `http://localhost:5000/register`
Expected: Registration form displays

**Step 6: Commit**

```bash
git add app.py templates/forgot_password.html
git commit -m "Add login, register, and logout routes"
```

---

## Task 7: Add user_id to Properties Table

**Files:**
- Modify: `database.py`
- Modify: `tests/test_database_users.py`

**Step 1: Write failing test for property with user_id**

Add to `tests/test_database_users.py`:

```python
from models import Property, PropertyType


def test_create_property_with_user_id(db):
    """Test creating property associated with a user."""
    # Create a user first
    user = User(email="test@example.com", password_hash="hashed", name="Test")
    user_id = db.create_user(user)

    # Create property for that user
    prop = Property(address="123 Test St", postcode="AB1 2CD", property_type=PropertyType.HOUSE)
    prop_id = db.create_property(prop, user_id=user_id)

    # Verify property belongs to user
    props = db.list_properties(user_id=user_id)
    assert len(props) == 1
    assert props[0].address == "123 Test St"


def test_list_properties_filters_by_user(db):
    """Test that list_properties only returns user's properties."""
    # Create two users
    user1_id = db.create_user(User(email="user1@example.com", password_hash="h", name="User 1"))
    user2_id = db.create_user(User(email="user2@example.com", password_hash="h", name="User 2"))

    # Create property for each
    db.create_property(Property(address="User 1 Property", postcode="A1 1AA"), user_id=user1_id)
    db.create_property(Property(address="User 2 Property", postcode="B2 2BB"), user_id=user2_id)

    # Each user should only see their own
    user1_props = db.list_properties(user_id=user1_id)
    user2_props = db.list_properties(user_id=user2_id)

    assert len(user1_props) == 1
    assert user1_props[0].address == "User 1 Property"
    assert len(user2_props) == 1
    assert user2_props[0].address == "User 2 Property"
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_database_users.py::test_create_property_with_user_id -v`
Expected: FAIL (missing user_id parameter or column)

**Step 3: Update properties table schema**

In `database.py`, update the properties table in SCHEMA:

```sql
-- Properties table
CREATE TABLE IF NOT EXISTS properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    address TEXT NOT NULL,
    postcode TEXT NOT NULL,
    property_type TEXT NOT NULL DEFAULT 'house',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

**Step 4: Update create_property method**

Find `create_property` method and update to:

```python
    def create_property(self, prop: Property, user_id: int) -> int:
        """Create a new property and return its ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                """INSERT INTO properties (user_id, address, postcode, property_type)
                   VALUES (?, ?, ?, ?)""",
                (user_id, prop.address, prop.postcode, prop.property_type.value),
            )
            return cursor.lastrowid
```

**Step 5: Update list_properties method**

Find `list_properties` method and update to:

```python
    def list_properties(self, user_id: int) -> list[Property]:
        """List all properties for a user."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM properties WHERE user_id = ? ORDER BY address",
                (user_id,),
            )
            return [
                Property(
                    id=row["id"],
                    address=row["address"],
                    postcode=row["postcode"],
                    property_type=PropertyType(row["property_type"]),
                    created_at=row["created_at"],
                )
                for row in cursor.fetchall()
            ]
```

**Step 6: Update get_property method**

Find `get_property` method and update to include user_id check:

```python
    def get_property(self, property_id: int, user_id: int) -> Optional[Property]:
        """Get a property by ID (only if it belongs to user)."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM properties WHERE id = ? AND user_id = ?",
                (property_id, user_id),
            )
            row = cursor.fetchone()
            if row:
                return Property(
                    id=row["id"],
                    address=row["address"],
                    postcode=row["postcode"],
                    property_type=PropertyType(row["property_type"]),
                    created_at=row["created_at"],
                )
            return None
```

**Step 7: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_database_users.py -v`
Expected: PASS (6 tests)

**Step 8: Commit**

```bash
git add database.py tests/test_database_users.py
git commit -m "Add user_id to properties table"
```

---

## Task 8: Add user_id to Remaining Tables

**Files:**
- Modify: `database.py`

**Step 1: Update tenancies table schema**

Update SCHEMA for tenancies table to add user_id:

```sql
-- Tenancies table
CREATE TABLE IF NOT EXISTS tenancies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    property_id INTEGER NOT NULL,
    -- ... rest of columns unchanged ...
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (property_id) REFERENCES properties(id)
);
```

**Step 2: Update certificates table schema**

```sql
-- Certificates table
CREATE TABLE IF NOT EXISTS certificates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    property_id INTEGER NOT NULL,
    -- ... rest of columns unchanged ...
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (property_id) REFERENCES properties(id)
);
```

**Step 3: Update compliance_events table schema**

```sql
-- Compliance events table
CREATE TABLE IF NOT EXISTS compliance_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    property_id INTEGER NOT NULL,
    -- ... rest of columns unchanged ...
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (property_id) REFERENCES properties(id),
    FOREIGN KEY (tenancy_id) REFERENCES tenancies(id)
);
```

**Step 4: Update served_documents table schema**

```sql
-- Documents served to tenants
CREATE TABLE IF NOT EXISTS served_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    tenancy_id INTEGER NOT NULL,
    -- ... rest of columns unchanged ...
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (tenancy_id) REFERENCES tenancies(id),
    UNIQUE(tenancy_id, document_type)
);
```

**Step 5: Update sent_reminders table in notifications.py**

In `services/notifications.py`, update the `_ensure_tables` method to add user_id:

```sql
-- Sent reminders tracking (prevent duplicate sends)
CREATE TABLE IF NOT EXISTS sent_reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    item_type TEXT NOT NULL,
    item_id INTEGER NOT NULL,
    reminder_days INTEGER NOT NULL,
    sent_date DATE NOT NULL,
    UNIQUE(user_id, item_type, item_id, reminder_days)
);
```

**Step 6: Commit**

```bash
git add database.py services/notifications.py
git commit -m "Add user_id to all tables"
```

---

## Task 9: Update All Database Methods for user_id

**Files:**
- Modify: `database.py`

This is a large task. Update each method to accept and filter by `user_id`. The pattern is:

1. Add `user_id: int` parameter
2. Add `user_id` to INSERT statements
3. Add `WHERE user_id = ?` to SELECT/UPDATE/DELETE statements

Methods to update:
- `create_tenancy`, `get_tenancy`, `list_tenancies`, `list_tenancies_for_property`, `delete_tenancy`
- `create_certificate`, `get_certificate`, `get_latest_certificate`, `update_certificate`
- `create_event`, `get_event`, `list_events`, `update_event`
- `mark_document_served`, `get_served_documents`, `delete_served_document`
- `delete_property`

**Step 1: Update tenancy methods**

Example for `create_tenancy`:

```python
    def create_tenancy(self, tenancy: Tenancy, user_id: int) -> int:
        """Create a new tenancy and return its ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                """INSERT INTO tenancies (
                    user_id, property_id, tenant_names, tenancy_start_date,
                    fixed_term_end_date, rent_amount, rent_frequency,
                    deposit_amount, deposit_protected, deposit_protection_date,
                    deposit_scheme, prescribed_info_served, prescribed_info_date,
                    how_to_rent_served, how_to_rent_date, is_active, document_path, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    tenancy.property_id,
                    # ... rest of fields
                ),
            )
            return cursor.lastrowid
```

**Step 2: Continue for all other methods**

Follow the same pattern for all database methods. Each query that touches user data must filter by user_id.

**Step 3: Run existing tests to check for breakage**

Run: `python3 -m pytest tests/ -v`
Note: Some tests may fail due to missing user_id - update tests as needed.

**Step 4: Commit**

```bash
git add database.py
git commit -m "Update all database methods to filter by user_id"
```

---

## Task 10: Update App Routes to Use current_user

**Files:**
- Modify: `app.py`

**Step 1: Add @login_required to all protected routes**

Add `@login_required` decorator to all routes except login, register, forgot_password.

**Step 2: Update routes to pass current_user.id**

Example for index route:

```python
@app.route("/")
@login_required
def index():
    """Dashboard showing overview with alerts."""
    db = get_db()
    user_id = current_user.id

    properties = db.list_properties(user_id=user_id)
    tenancies = db.list_tenancies(user_id=user_id, active_only=True)
    # ... rest of route
```

**Step 3: Update all routes similarly**

Every route that accesses the database needs to pass `user_id=current_user.id`.

**Step 4: Update base.html to show user info**

In `templates/base.html`, update the header to show logged-in user:

```html
<nav>
    <a href="{{ url_for('index') }}">Dashboard</a>
    <a href="{{ url_for('properties') }}">Properties</a>
    <a href="{{ url_for('tenancies') }}">Tenancies</a>
    <a href="{{ url_for('timeline') }}">Timeline</a>
    {% if current_user.is_authenticated %}
        <a href="{{ url_for('account') }}">{{ current_user.name }}</a>
        <a href="{{ url_for('logout') }}">Logout</a>
    {% endif %}
</nav>
```

**Step 5: Test manually**

Run: `python3 app.py`
1. Visit http://localhost:5000/ - should redirect to login
2. Register a new account
3. Should redirect to dashboard
4. Add a property, verify it appears
5. Logout, login as different user, verify no properties visible

**Step 6: Commit**

```bash
git add app.py templates/base.html
git commit -m "Protect all routes and pass user_id to database"
```

---

## Task 11: Add Account Page

**Files:**
- Create: `templates/account.html`
- Modify: `app.py`

**Step 1: Create account.html**

Create `templates/account.html`:

```html
{% extends "base.html" %}

{% block title %}Account - Landlord Command Centre{% endblock %}

{% block content %}
<h1>Account</h1>

<div class="detail-grid">
    <div class="card">
        <h2>Your Details</h2>

        <form method="POST" action="{{ url_for('update_account') }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

            <div class="form-group">
                <label for="name">Name</label>
                <input type="text" id="name" name="name" value="{{ current_user.name }}" required>
            </div>

            <div class="form-group">
                <label for="email">Email</label>
                <input type="email" id="email" value="{{ current_user.email }}" disabled>
                <small style="color: #666;">Email cannot be changed</small>
            </div>

            <button type="submit" class="btn btn-success">Save Changes</button>
        </form>
    </div>

    <div class="card">
        <h2>Change Password</h2>

        <form method="POST" action="{{ url_for('change_password') }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">

            <div class="form-group">
                <label for="current_password">Current Password</label>
                <input type="password" id="current_password" name="current_password" required>
            </div>

            <div class="form-group">
                <label for="new_password">New Password</label>
                <input type="password" id="new_password" name="new_password" required minlength="8">
            </div>

            <div class="form-group">
                <label for="confirm_password">Confirm New Password</label>
                <input type="password" id="confirm_password" name="confirm_password" required>
            </div>

            <button type="submit" class="btn">Change Password</button>
        </form>
    </div>

    <div class="card">
        <h2>Email Reminders</h2>
        <p style="color: #666;">
            Reminder emails are sent to <strong>{{ current_user.email }}</strong> when certificates are expiring.
        </p>
        <p>
            You'll be notified at 3 months, 2 months, 4 weeks, 3 weeks, 2 weeks, and 1 week before expiry.
        </p>

        {% if pending_reminders %}
        <h3 style="margin-top: 1.5rem;">Upcoming Reminders</h3>
        <table>
            <thead>
                <tr>
                    <th>Item</th>
                    <th>Property</th>
                    <th>Expires</th>
                </tr>
            </thead>
            <tbody>
                {% for item in pending_reminders %}
                <tr>
                    <td>{{ item.name }}</td>
                    <td>{{ item.property_address }}</td>
                    <td>{{ item.expiry_date.strftime('%d %b %Y') }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
        {% else %}
        <p style="color: #27ae60; margin-top: 1rem;">
            No reminders due - nothing expiring within 3 months.
        </p>
        {% endif %}
    </div>
</div>
{% endblock %}
```

**Step 2: Add account routes to app.py**

```python
@app.route("/account")
@login_required
def account():
    """Account settings page."""
    db = get_db()
    notifications = NotificationService(db)
    pending = notifications.get_pending_reminders_preview(user_id=current_user.id)
    return render_template("account.html", pending_reminders=pending)


@app.route("/account/update", methods=["POST"])
@login_required
def update_account():
    """Update account details."""
    name = request.form.get("name", "").strip()
    if not name:
        flash("Name is required", "error")
        return redirect(url_for("account"))

    db = get_db()
    db.update_user(current_user.id, name=name)
    flash("Account updated", "success")
    return redirect(url_for("account"))


@app.route("/account/password", methods=["POST"])
@login_required
def change_password():
    """Change password."""
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not check_password(current_password, current_user.password_hash):
        flash("Current password is incorrect", "error")
        return redirect(url_for("account"))

    if len(new_password) < 8:
        flash("New password must be at least 8 characters", "error")
        return redirect(url_for("account"))

    if new_password != confirm_password:
        flash("New passwords do not match", "error")
        return redirect(url_for("account"))

    db = get_db()
    db.update_user(current_user.id, password_hash=hash_password(new_password))
    flash("Password changed successfully", "success")
    return redirect(url_for("account"))
```

**Step 3: Add update_user method to database.py**

```python
    def update_user(self, user_id: int, name: str = None, password_hash: str = None) -> None:
        """Update user details."""
        with self.connection() as conn:
            if name is not None:
                conn.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))
            if password_hash is not None:
                conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
```

**Step 4: Remove old settings route**

Remove or rename the old `/settings` route since it's replaced by `/account`.

**Step 5: Commit**

```bash
git add templates/account.html app.py database.py
git commit -m "Add account page with name update and password change"
```

---

## Task 12: Update Notifications for Multi-User

**Files:**
- Modify: `services/notifications.py`

**Step 1: Update NotificationService methods to accept user_id**

Update `get_expiring_items` to filter by user:

```python
    def get_expiring_items(self, user_id: int) -> list[ExpiryItem]:
        """Get all items that need reminders for a user."""
        today = date.today()
        items = []

        # Check certificates for user's properties
        for cert_type in CertificateType:
            items.extend(self._get_expiring_certificates(cert_type, today, user_id))

        # Check compliance events
        items.extend(self._get_expiring_events(today, user_id))

        return items
```

**Step 2: Update send_reminders for all users**

```python
    def send_reminders_for_all_users(self) -> dict:
        """Check all users and send reminders. Called by cron job."""
        results = []

        # Get all users
        with self.db.connection() as conn:
            cursor = conn.execute("SELECT id, email, name FROM users WHERE is_active = 1")
            users = cursor.fetchall()

        for user in users:
            user_id = user["id"]
            email = user["email"]

            items = self.get_expiring_items(user_id)
            if items:
                # Build and send email
                subject = f"Landlord Compliance Reminders - {len(items)} item(s) expiring"
                body = self._build_email_body(self._group_items(items))

                try:
                    self._send_email(email, subject, body)
                    self._mark_reminders_sent(items, user_id)
                    results.append({"user": email, "sent": len(items)})
                except Exception as e:
                    results.append({"user": email, "error": str(e)})

        return {"status": "ok", "results": results}
```

**Step 3: Commit**

```bash
git add services/notifications.py
git commit -m "Update notifications service for multi-user"
```

---

## Task 13: Final Testing and Cleanup

**Step 1: Run all tests**

Run: `python3 -m pytest tests/ -v`
Expected: All tests pass

**Step 2: Manual testing checklist**

1. Register new user → dashboard shows empty
2. Add property → appears in list
3. Add tenancy → timeline events generated
4. Logout → redirected to login
5. Register second user → sees empty dashboard
6. First user's data not visible to second user
7. Account page → can change name and password

**Step 3: Remove old settings references**

Search for any remaining references to old `/settings` route and update to `/account`.

**Step 4: Final commit**

```bash
git add -A
git commit -m "Complete multi-user authentication implementation"
```

---

## Summary

This plan implements:
- User registration and login with email/password
- Password hashing with bcrypt
- Session management with Flask-Login
- CSRF protection with Flask-WTF
- Per-user data isolation (user_id on all tables)
- Account page with password change
- Automatic email reminders to user's registered email

**Next steps after this plan:**
1. Deploy to Railway with PostgreSQL
2. Add password reset email functionality
3. Add rate limiting on login
