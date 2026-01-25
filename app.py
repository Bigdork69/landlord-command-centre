"""Flask web interface for Landlord Command Centre."""

import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename

from config import get_config
from services.auth import hash_password, check_password
from models import User
from database import Database
from models import Certificate, CertificateType, EventPriority, EventStatus, Property, PropertyType, RentFrequency, RequiredDocument, Tenancy
from parsers.tenancy import TenancyParser
from parsers.gas_safety import GasSafetyParser
from parsers.eicr import EICRParser
from parsers.epc import EPCParser
from services.timeline import TimelineGenerator
from services.notifications import NotificationService

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-prod")

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


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Request password reset."""
    if request.method == "POST":
        flash("If that email exists, a reset link has been sent.", "success")
        return redirect(url_for("login"))
    return render_template("forgot_password.html")


# File upload config
UPLOAD_FOLDER = Path(__file__).parent / "uploads"
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


_db_instance = None
_db_initialized = False

def get_db() -> Database:
    """Get database instance (singleton, initialized once)."""
    global _db_instance, _db_initialized
    if _db_instance is None:
        config = get_config()
        config.ensure_directories()
        _db_instance = Database(config.database_path)
    if not _db_initialized:
        _db_instance.initialize()
        _db_initialized = True
    return _db_instance


@app.route("/")
@login_required
def index():
    """Dashboard showing overview with alerts."""
    db = get_db()
    user_id = current_user.id

    # Auto-send reminders for current user (silent operation)
    notifications = NotificationService(db)
    notifications.send_reminders(user_id=user_id, user_email=current_user.email)

    properties = db.list_properties(user_id=user_id)
    tenancies = db.list_tenancies(user_id=user_id, active_only=True)

    # Calculate stats
    total_rent = sum(t.rent_amount for t in tenancies)

    # Get timeline alerts
    timeline = TimelineGenerator(db, user_id=user_id)
    overdue_events = timeline.get_overdue_events()
    upcoming_events = timeline.get_upcoming_events(days=14)

    # Filter out overdue from upcoming to avoid duplicates
    overdue_ids = {e.id for e in overdue_events}
    upcoming_events = [e for e in upcoming_events if e.id not in overdue_ids]

    return render_template(
        "index.html",
        properties=properties,
        tenancies=tenancies,
        total_rent=total_rent,
        property_count=len(properties),
        tenancy_count=len(tenancies),
        overdue_events=overdue_events,
        upcoming_events=upcoming_events[:5],  # Top 5
    )


@app.route("/properties")
@login_required
def properties():
    """List all properties."""
    db = get_db()
    user_id = current_user.id
    properties = db.list_properties(user_id=user_id)
    return render_template("properties.html", properties=properties)


@app.route("/properties/add", methods=["GET", "POST"])
@login_required
def add_property():
    """Add a new property."""
    if request.method == "POST":
        db = get_db()
        user_id = current_user.id
        prop = Property(
            address=request.form["address"],
            postcode=request.form["postcode"].upper(),
            property_type=PropertyType(request.form["property_type"]),
        )
        prop_id = db.create_property(prop, user_id=user_id)
        flash(f"Property added successfully! You can now add tenants and certificates.", "success")
        return redirect(url_for("properties"))

    return render_template("add_property.html", property_types=PropertyType)


@app.route("/properties/<int:property_id>")
@login_required
def property_detail(property_id: int):
    """Show property details with documents and timeline."""
    db = get_db()
    user_id = current_user.id
    prop = db.get_property(property_id, user_id=user_id)
    if not prop:
        flash("Property not found", "error")
        return redirect(url_for("properties"))

    tenancies = db.list_tenancies_for_property(property_id, user_id=user_id)

    # Get certificates
    certificates = {
        'gas_safety': db.get_latest_certificate(property_id, CertificateType.GAS_SAFETY, user_id=user_id),
        'eicr': db.get_latest_certificate(property_id, CertificateType.EICR, user_id=user_id),
        'epc': db.get_latest_certificate(property_id, CertificateType.EPC, user_id=user_id),
    }

    # Add rating to EPC certificate for template display
    if certificates['epc'] and certificates['epc'].notes:
        # Rating stored in notes as "Rating: X"
        import re
        rating_match = re.search(r'Rating:\s*([A-G])', certificates['epc'].notes)
        if rating_match:
            certificates['epc'].rating = rating_match.group(1)
        else:
            certificates['epc'].rating = None
    elif certificates['epc']:
        certificates['epc'].rating = None

    # Get compliance events for this property
    events = db.list_events(user_id=user_id, property_id=property_id)

    return render_template(
        "property_detail.html",
        property=prop,
        tenancies=tenancies,
        certificates=certificates,
        events=events,
        today=date.today(),
        EventStatus=EventStatus,
        EventPriority=EventPriority,
    )


@app.route("/properties/<int:property_id>/delete", methods=["POST"])
@login_required
def delete_property(property_id: int):
    """Delete a property and all associated data."""
    db = get_db()
    user_id = current_user.id
    prop = db.get_property(property_id, user_id=user_id)
    if not prop:
        flash("Property not found", "error")
        return redirect(url_for("properties"))

    address = prop.address
    db.delete_property(property_id, user_id=user_id)
    flash(f"Property '{address}' and all associated data deleted", "success")
    return redirect(url_for("properties"))


@app.route("/properties/<int:property_id>/upload-certificate", methods=["POST"])
@login_required
def upload_certificate(property_id: int):
    """Upload and parse a compliance certificate PDF."""
    db = get_db()
    user_id = current_user.id
    prop = db.get_property(property_id, user_id=user_id)
    if not prop:
        flash("Property not found", "error")
        return redirect(url_for("properties"))

    # Check file uploaded
    if "file" not in request.files:
        flash("No file uploaded", "error")
        return redirect(url_for("property_detail", property_id=property_id))

    file = request.files["file"]
    if file.filename == "":
        flash("No file selected", "error")
        return redirect(url_for("property_detail", property_id=property_id))

    cert_type = request.form.get("cert_type", "gas_safety")

    if file and allowed_file(file.filename):
        # Save file
        UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
        filename = secure_filename(file.filename)
        filepath = UPLOAD_FOLDER / f"{cert_type}_{property_id}_{filename}"
        file.save(filepath)

        try:
            # Select parser based on certificate type
            parsers = {
                'gas_safety': GasSafetyParser(),
                'eicr': EICRParser(),
                'epc': EPCParser(),
            }
            parser = parsers.get(cert_type)
            if not parser:
                flash(f"Unknown certificate type: {cert_type}", "error")
                return redirect(url_for("property_detail", property_id=property_id))

            # Parse the file
            result = parser.parse(filepath)

            # Get dates - prefer manual entry over parsed values
            manual_issue = request.form.get('issue_date')
            manual_expiry = request.form.get('expiry_date')

            if manual_issue:
                from datetime import datetime
                issue_date = datetime.strptime(manual_issue, '%Y-%m-%d').date()
            else:
                issue_date = result.extracted_fields.get('issue_date')

            if manual_expiry:
                from datetime import datetime
                expiry_date = datetime.strptime(manual_expiry, '%Y-%m-%d').date()
            else:
                expiry_date = result.extracted_fields.get('expiry_date')

            # Build notes with extra info
            notes_parts = []
            if cert_type == 'epc':
                # Prefer manual rating over parsed
                rating = request.form.get('rating') or result.extracted_fields.get('rating')
                if rating:
                    notes_parts.append(f"Rating: {rating}")
                score = result.extracted_fields.get('score')
                if score:
                    notes_parts.append(f"Score: {score}")
            if cert_type == 'gas_safety':
                gas_safe = result.extracted_fields.get('gas_safe_number')
                if gas_safe:
                    notes_parts.append(f"Gas Safe: {gas_safe}")
            if cert_type == 'eicr':
                satisfactory = result.extracted_fields.get('satisfactory')
                if satisfactory is not None:
                    notes_parts.append(f"Satisfactory: {'Yes' if satisfactory else 'NO - REMEDIAL WORK REQUIRED'}")

            # Create certificate record
            cert_type_map = {
                'gas_safety': CertificateType.GAS_SAFETY,
                'eicr': CertificateType.EICR,
                'epc': CertificateType.EPC,
            }

            cert = Certificate(
                property_id=property_id,
                certificate_type=cert_type_map[cert_type],
                issue_date=issue_date,
                expiry_date=expiry_date,
                document_path=str(filepath),
                notes="; ".join(notes_parts) if notes_parts else "",
            )
            cert_id = db.create_certificate(cert, user_id=user_id)

            # Show warnings if any
            if result.warnings:
                for warning in result.warnings[:3]:  # Limit to 3 warnings
                    flash(warning, "warning")

            if issue_date and expiry_date:
                flash(f"Certificate uploaded successfully! Valid until {expiry_date}.", "success")
            elif issue_date:
                flash(f"Certificate uploaded! Issued {issue_date}. Please verify expiry date.", "warning")
            else:
                flash("Certificate uploaded but dates could not be extracted. Please add manually.", "warning")

        except Exception as e:
            flash(f"Error processing certificate: {e}", "error")
            filepath.unlink(missing_ok=True)

    else:
        flash("Only PDF, JPG, and PNG files are allowed", "error")

    return redirect(url_for("property_detail", property_id=property_id))


@app.route("/certificates/<int:cert_id>/update", methods=["POST"])
@login_required
def update_certificate(cert_id: int):
    """Update certificate dates manually."""
    db = get_db()
    user_id = current_user.id
    cert = db.get_certificate(cert_id, user_id=user_id)

    if not cert:
        flash("Certificate not found", "error")
        return redirect(url_for("properties"))

    # Parse dates from form
    issue_date = None
    expiry_date = None
    notes = None

    if request.form.get('issue_date'):
        from datetime import datetime
        issue_date = datetime.strptime(request.form['issue_date'], '%Y-%m-%d').date()

    if request.form.get('expiry_date'):
        from datetime import datetime
        expiry_date = datetime.strptime(request.form['expiry_date'], '%Y-%m-%d').date()

    # Handle EPC rating
    if request.form.get('rating'):
        rating = request.form['rating']
        existing_notes = cert.notes or ""
        if "Rating:" in existing_notes:
            import re
            notes = re.sub(r'Rating: [A-G]', f'Rating: {rating}', existing_notes)
        else:
            notes = f"Rating: {rating}; {existing_notes}" if existing_notes else f"Rating: {rating}"

    db.update_certificate(cert_id, user_id=user_id, issue_date=issue_date, expiry_date=expiry_date, notes=notes)
    flash("Certificate dates saved successfully!", "success")

    return redirect(url_for("property_detail", property_id=cert.property_id))


@app.route("/tenancies")
@login_required
def tenancies():
    """List all tenancies."""
    db = get_db()
    user_id = current_user.id
    tenancy_list = db.list_tenancies(user_id=user_id)

    tenancies_with_props = []
    for t in tenancy_list:
        prop = db.get_property(t.property_id, user_id=user_id)
        tenancies_with_props.append({"tenancy": t, "property": prop})

    return render_template("tenancies.html", tenancies=tenancies_with_props)


@app.route("/tenancies/add", methods=["GET", "POST"])
@login_required
def add_tenancy():
    """Add a new tenancy manually."""
    db = get_db()
    user_id = current_user.id

    if request.method == "POST":
        try:
            start_date = date.fromisoformat(request.form["tenancy_start_date"])
            end_date = None
            if request.form.get("fixed_term_end_date"):
                end_date = date.fromisoformat(request.form["fixed_term_end_date"])

            rent_amount = Decimal(request.form["rent_amount"].replace(",", "").replace("£", ""))
            deposit_amount = Decimal(request.form.get("deposit_amount", "0").replace(",", "").replace("£", "") or "0")

            tenancy = Tenancy(
                property_id=int(request.form["property_id"]),
                tenant_names=request.form["tenant_names"],
                tenancy_start_date=start_date,
                fixed_term_end_date=end_date,
                rent_amount=rent_amount,
                rent_frequency=RentFrequency(request.form["rent_frequency"]),
                deposit_amount=deposit_amount,
            )
            tenancy_id = db.create_tenancy(tenancy, user_id=user_id)

            # Generate compliance timeline
            tenancy = db.get_tenancy(tenancy_id, user_id=user_id)
            timeline = TimelineGenerator(db, user_id=user_id)
            events = timeline.generate_for_tenancy(tenancy)

            flash(f"Tenancy added successfully! We've created {len(events)} compliance reminders for you.", "success")
            return redirect(url_for("tenancy_detail", tenancy_id=tenancy_id))
        except Exception as e:
            flash(f"Error creating tenancy: {e}", "error")

    properties = db.list_properties(user_id=user_id)
    return render_template(
        "add_tenancy.html",
        properties=properties,
        rent_frequencies=RentFrequency,
    )


@app.route("/tenancies/upload", methods=["GET", "POST"])
@login_required
def upload_tenancy():
    """Upload and parse a tenancy agreement PDF."""
    db = get_db()
    user_id = current_user.id
    properties = db.list_properties(user_id=user_id)

    if request.method == "POST":
        # Check if file was uploaded
        if "file" not in request.files:
            flash("No file uploaded", "error")
            return redirect(request.url)

        file = request.files["file"]
        if file.filename == "":
            flash("No file selected", "error")
            return redirect(request.url)

        if file and allowed_file(file.filename):
            # Save file temporarily
            UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
            filename = secure_filename(file.filename)
            filepath = UPLOAD_FOLDER / filename
            file.save(filepath)

            try:
                # Parse the PDF
                parser = TenancyParser()
                result = parser.parse(filepath)

                # Store in session for confirmation
                return render_template(
                    "confirm_tenancy.html",
                    properties=properties,
                    rent_frequencies=RentFrequency,
                    extracted=result.extracted_fields,
                    confidence=result.confidence_scores,
                    warnings=result.warnings,
                    filepath=str(filepath),
                )
            except Exception as e:
                flash(f"Error parsing PDF: {e}", "error")
                filepath.unlink(missing_ok=True)
                return redirect(request.url)
        else:
            flash("Only PDF files are allowed", "error")
            return redirect(request.url)

    return render_template("upload_tenancy.html", properties=properties)


@app.route("/tenancies/confirm", methods=["POST"])
@login_required
def confirm_tenancy():
    """Confirm and save parsed tenancy data."""
    db = get_db()
    user_id = current_user.id

    try:
        start_date = date.fromisoformat(request.form["tenancy_start_date"]) if request.form.get("tenancy_start_date") else None
        end_date = date.fromisoformat(request.form["fixed_term_end_date"]) if request.form.get("fixed_term_end_date") else None

        rent_str = request.form.get("rent_amount", "0").replace(",", "").replace("£", "") or "0"
        rent_amount = Decimal(rent_str)

        deposit_str = request.form.get("deposit_amount", "0").replace(",", "").replace("£", "") or "0"
        deposit_amount = Decimal(deposit_str)

        # Check if we need to create a new property
        property_id = request.form.get("property_id")
        if property_id == "new" or not property_id:
            # Create new property
            address = request.form.get("property_address", "Unknown Address")
            postcode = request.form.get("postcode", "").upper()
            prop = Property(
                address=address,
                postcode=postcode,
                property_type=PropertyType.HOUSE,
            )
            property_id = db.create_property(prop, user_id=user_id)
        else:
            property_id = int(property_id)

        tenancy = Tenancy(
            property_id=property_id,
            tenant_names=request.form.get("tenant_names", "Unknown"),
            tenancy_start_date=start_date,
            fixed_term_end_date=end_date,
            rent_amount=rent_amount,
            rent_frequency=RentFrequency(request.form.get("rent_frequency", "monthly")),
            deposit_amount=deposit_amount,
            document_path=request.form.get("filepath", ""),
        )
        tenancy_id = db.create_tenancy(tenancy, user_id=user_id)

        # Generate compliance timeline
        tenancy = db.get_tenancy(tenancy_id, user_id=user_id)
        timeline = TimelineGenerator(db, user_id=user_id)
        events = timeline.generate_for_tenancy(tenancy)

        flash(f"Tenancy added from PDF! We've created {len(events)} compliance reminders for you.", "success")
        return redirect(url_for("tenancy_detail", tenancy_id=tenancy_id))

    except Exception as e:
        flash(f"Error saving tenancy: {e}", "error")
        return redirect(url_for("upload_tenancy"))


@app.route("/tenancies/<int:tenancy_id>")
@login_required
def tenancy_detail(tenancy_id: int):
    """Show tenancy details with compliance timeline."""
    db = get_db()
    user_id = current_user.id
    tenancy = db.get_tenancy(tenancy_id, user_id=user_id)
    if not tenancy:
        flash("Tenancy not found", "error")
        return redirect(url_for("tenancies"))

    prop = db.get_property(tenancy.property_id, user_id=user_id)

    # Get compliance events for this tenancy
    events = db.list_events(user_id=user_id, tenancy_id=tenancy_id)

    # Get served documents
    served_docs = db.get_served_documents(tenancy_id, user_id=user_id)
    served_doc_types = {doc.document_type.value: doc for doc in served_docs}

    return render_template(
        "tenancy_detail.html",
        tenancy=tenancy,
        property=prop,
        events=events,
        EventStatus=EventStatus,
        EventPriority=EventPriority,
        RequiredDocument=RequiredDocument,
        served_documents=served_doc_types,
        today=date.today(),
    )


@app.route("/tenancies/<int:tenancy_id>/serve-document", methods=["POST"])
@login_required
def serve_document(tenancy_id: int):
    """Mark a document as served to tenant."""
    db = get_db()
    user_id = current_user.id
    tenancy = db.get_tenancy(tenancy_id, user_id=user_id)
    if not tenancy:
        flash("Tenancy not found", "error")
        return redirect(url_for("tenancies"))

    doc_type = request.form.get("document_type")
    served_date_str = request.form.get("served_date")

    if not doc_type or not served_date_str:
        flash("Please provide document type and date", "error")
        return redirect(url_for("tenancy_detail", tenancy_id=tenancy_id))

    try:
        document_type = RequiredDocument(doc_type)
        from datetime import datetime
        served_date = datetime.strptime(served_date_str, '%Y-%m-%d').date()

        db.mark_document_served(tenancy_id, document_type, served_date, user_id=user_id)
        flash(f"{document_type.display_name} marked as served on {served_date.strftime('%d %b %Y')}", "success")
    except ValueError as e:
        flash(f"Invalid document type or date: {e}", "error")

    return redirect(url_for("tenancy_detail", tenancy_id=tenancy_id))


@app.route("/tenancies/<int:tenancy_id>/unserve-document", methods=["POST"])
@login_required
def unserve_document(tenancy_id: int):
    """Remove served status from a document."""
    db = get_db()
    user_id = current_user.id
    tenancy = db.get_tenancy(tenancy_id, user_id=user_id)
    if not tenancy:
        flash("Tenancy not found", "error")
        return redirect(url_for("tenancies"))

    doc_type = request.form.get("document_type")
    if doc_type:
        try:
            document_type = RequiredDocument(doc_type)
            db.delete_served_document(tenancy_id, document_type, user_id=user_id)
            flash(f"{document_type.display_name} unmarked", "success")
        except ValueError:
            flash("Invalid document type", "error")

    return redirect(url_for("tenancy_detail", tenancy_id=tenancy_id))


@app.route("/tenancies/<int:tenancy_id>/delete", methods=["POST"])
@login_required
def delete_tenancy(tenancy_id: int):
    """Delete a tenancy and its associated compliance events."""
    db = get_db()
    user_id = current_user.id
    tenancy = db.get_tenancy(tenancy_id, user_id=user_id)
    if not tenancy:
        flash("Tenancy not found", "error")
        return redirect(url_for("tenancies"))

    property_id = tenancy.property_id
    tenant_name = tenancy.tenant_names
    db.delete_tenancy(tenancy_id, user_id=user_id)
    flash(f"Tenancy for '{tenant_name}' deleted", "success")
    return redirect(url_for("property_detail", property_id=property_id))


@app.route("/timeline")
@login_required
def timeline():
    """Show full compliance timeline."""
    db = get_db()
    user_id = current_user.id
    tl = TimelineGenerator(db, user_id=user_id)

    # Get filter parameters
    days = int(request.args.get("days", 90))
    property_id = request.args.get("property_id", type=int)

    overdue = tl.get_overdue_events(property_id=property_id)
    upcoming = tl.get_upcoming_events(days=days, property_id=property_id)

    # Remove overdue from upcoming
    overdue_ids = {e.id for e in overdue}
    upcoming = [e for e in upcoming if e.id not in overdue_ids]

    # Get all properties for filter dropdown
    properties = db.list_properties(user_id=user_id)

    return render_template(
        "timeline.html",
        overdue=overdue,
        upcoming=upcoming,
        properties=properties,
        selected_property_id=property_id,
        selected_days=days,
        EventStatus=EventStatus,
        EventPriority=EventPriority,
        today=date.today(),
    )


@app.route("/events/<int:event_id>/complete", methods=["POST"])
@login_required
def complete_event(event_id: int):
    """Mark an event as completed."""
    db = get_db()
    user_id = current_user.id
    tl = TimelineGenerator(db, user_id=user_id)
    tl.mark_complete(event_id)
    flash("Task completed! Well done.", "success")

    # Redirect back to referring page
    return redirect(request.referrer or url_for("timeline"))


@app.route("/settings")
@login_required
def settings():
    """Redirect to account page."""
    return redirect(url_for("account"))


@app.route("/account")
@login_required
def account():
    """Account settings page."""
    db = get_db()
    user_id = current_user.id
    notifications = NotificationService(db)
    pending = notifications.get_pending_reminders_preview(user_id=user_id)
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
    flash("Account updated successfully!", "success")
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


@app.route("/send-reminders", methods=["POST"])
@login_required
def send_reminders():
    """Send reminder emails for current user's expiring items."""
    db = get_db()
    notifications = NotificationService(db)
    result = notifications.send_reminders(user_id=current_user.id, user_email=current_user.email)

    # Return JSON for API use
    if request.headers.get("Accept") == "application/json":
        return result

    # Flash message for web UI
    if result["status"] == "ok":
        if result["sent"] > 0:
            flash(f"Sent {result['sent']} reminder(s) to {current_user.email}", "success")
        else:
            flash("No reminders needed - nothing expiring soon", "success")
    else:
        flash(f"Error sending reminders: {result.get('message', 'Unknown error')}", "error")

    return redirect(url_for("account"))


@app.route("/send-test-reminders", methods=["POST"])
@login_required
def send_test_reminders():
    """Send test reminder email with current pending items to current user."""
    db = get_db()
    notifications = NotificationService(db)

    result = notifications.send_reminders(user_id=current_user.id, user_email=current_user.email)

    if result["status"] == "ok":
        if result["sent"] > 0:
            flash(f"Test email sent to {current_user.email}", "success")
        else:
            flash("No items expiring within 3 months - nothing to send", "success")
    else:
        flash(f"Error: {result.get('message', 'Failed to send email')}", "error")

    return redirect(url_for("account"))


@app.route("/health")
def health_check():
    """Health check endpoint showing database status."""
    try:
        db = get_db()
        db_type = "PostgreSQL" if db.use_postgres else "SQLite"
        with db.connection() as conn:
            conn.execute("SELECT 1")
            result = conn.fetchone()
        return {
            "status": "ok",
            "database": db_type,
            "database_url_set": bool(os.environ.get("DATABASE_URL")),
            "connection": "success"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "database_url_set": bool(os.environ.get("DATABASE_URL"))
        }, 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
