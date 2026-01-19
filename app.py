"""Flask web interface for Landlord Command Centre."""

import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from config import get_config
from database import Database
from models import Certificate, CertificateType, EventPriority, EventStatus, Property, PropertyType, RentFrequency, Tenancy
from parsers.tenancy import TenancyParser
from parsers.gas_safety import GasSafetyParser
from parsers.eicr import EICRParser
from parsers.epc import EPCParser
from services.timeline import TimelineGenerator

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-prod")

# File upload config
UPLOAD_FOLDER = Path(__file__).parent / "uploads"
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def get_db() -> Database:
    """Get database instance."""
    config = get_config()
    config.ensure_directories()
    db = Database(config.database_path)
    db.initialize()
    return db


@app.route("/")
def index():
    """Dashboard showing overview with alerts."""
    db = get_db()
    properties = db.list_properties()
    tenancies = db.list_tenancies(active_only=True)

    # Calculate stats
    total_rent = sum(t.rent_amount for t in tenancies)

    # Get timeline alerts
    timeline = TimelineGenerator(db)
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
def properties():
    """List all properties."""
    db = get_db()
    properties = db.list_properties()
    return render_template("properties.html", properties=properties)


@app.route("/properties/add", methods=["GET", "POST"])
def add_property():
    """Add a new property."""
    if request.method == "POST":
        db = get_db()
        prop = Property(
            address=request.form["address"],
            postcode=request.form["postcode"].upper(),
            property_type=PropertyType(request.form["property_type"]),
        )
        prop_id = db.create_property(prop)
        flash(f"Property created with ID: {prop_id}", "success")
        return redirect(url_for("properties"))

    return render_template("add_property.html", property_types=PropertyType)


@app.route("/properties/<int:property_id>")
def property_detail(property_id: int):
    """Show property details with documents and timeline."""
    db = get_db()
    prop = db.get_property(property_id)
    if not prop:
        flash("Property not found", "error")
        return redirect(url_for("properties"))

    tenancies = db.list_tenancies_for_property(property_id)

    # Get certificates
    certificates = {
        'gas_safety': db.get_latest_certificate(property_id, CertificateType.GAS_SAFETY),
        'eicr': db.get_latest_certificate(property_id, CertificateType.EICR),
        'epc': db.get_latest_certificate(property_id, CertificateType.EPC),
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
    events = db.list_events(property_id=property_id)

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
def delete_property(property_id: int):
    """Delete a property and all associated data."""
    db = get_db()
    prop = db.get_property(property_id)
    if not prop:
        flash("Property not found", "error")
        return redirect(url_for("properties"))

    address = prop.address
    db.delete_property(property_id)
    flash(f"Property '{address}' and all associated data deleted", "success")
    return redirect(url_for("properties"))


@app.route("/properties/<int:property_id>/upload-certificate", methods=["POST"])
def upload_certificate(property_id: int):
    """Upload and parse a compliance certificate PDF."""
    db = get_db()
    prop = db.get_property(property_id)
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
            cert_id = db.create_certificate(cert)

            # Show warnings if any
            if result.warnings:
                for warning in result.warnings[:3]:  # Limit to 3 warnings
                    flash(warning, "warning")

            if issue_date and expiry_date:
                flash(f"Certificate uploaded! Valid from {issue_date} to {expiry_date}", "success")
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


@app.route("/tenancies")
def tenancies():
    """List all tenancies."""
    db = get_db()
    tenancy_list = db.list_tenancies()

    tenancies_with_props = []
    for t in tenancy_list:
        prop = db.get_property(t.property_id)
        tenancies_with_props.append({"tenancy": t, "property": prop})

    return render_template("tenancies.html", tenancies=tenancies_with_props)


@app.route("/tenancies/add", methods=["GET", "POST"])
def add_tenancy():
    """Add a new tenancy manually."""
    db = get_db()

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
            tenancy_id = db.create_tenancy(tenancy)

            # Generate compliance timeline
            tenancy = db.get_tenancy(tenancy_id)
            timeline = TimelineGenerator(db)
            events = timeline.generate_for_tenancy(tenancy)

            flash(f"Tenancy created! Generated {len(events)} compliance deadlines.", "success")
            return redirect(url_for("tenancy_detail", tenancy_id=tenancy_id))
        except Exception as e:
            flash(f"Error creating tenancy: {e}", "error")

    properties = db.list_properties()
    return render_template(
        "add_tenancy.html",
        properties=properties,
        rent_frequencies=RentFrequency,
    )


@app.route("/tenancies/upload", methods=["GET", "POST"])
def upload_tenancy():
    """Upload and parse a tenancy agreement PDF."""
    db = get_db()
    properties = db.list_properties()

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
def confirm_tenancy():
    """Confirm and save parsed tenancy data."""
    db = get_db()

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
            property_id = db.create_property(prop)
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
        tenancy_id = db.create_tenancy(tenancy)

        # Generate compliance timeline
        tenancy = db.get_tenancy(tenancy_id)
        timeline = TimelineGenerator(db)
        events = timeline.generate_for_tenancy(tenancy)

        flash(f"Tenancy created from PDF! Generated {len(events)} compliance deadlines.", "success")
        return redirect(url_for("tenancy_detail", tenancy_id=tenancy_id))

    except Exception as e:
        flash(f"Error saving tenancy: {e}", "error")
        return redirect(url_for("upload_tenancy"))


@app.route("/tenancies/<int:tenancy_id>")
def tenancy_detail(tenancy_id: int):
    """Show tenancy details with compliance timeline."""
    db = get_db()
    tenancy = db.get_tenancy(tenancy_id)
    if not tenancy:
        flash("Tenancy not found", "error")
        return redirect(url_for("tenancies"))

    prop = db.get_property(tenancy.property_id)

    # Get compliance events for this tenancy
    events = db.list_events(tenancy_id=tenancy_id)

    return render_template(
        "tenancy_detail.html",
        tenancy=tenancy,
        property=prop,
        events=events,
        EventStatus=EventStatus,
        EventPriority=EventPriority,
    )


@app.route("/tenancies/<int:tenancy_id>/delete", methods=["POST"])
def delete_tenancy(tenancy_id: int):
    """Delete a tenancy and its associated compliance events."""
    db = get_db()
    tenancy = db.get_tenancy(tenancy_id)
    if not tenancy:
        flash("Tenancy not found", "error")
        return redirect(url_for("tenancies"))

    property_id = tenancy.property_id
    tenant_name = tenancy.tenant_names
    db.delete_tenancy(tenancy_id)
    flash(f"Tenancy for '{tenant_name}' deleted", "success")
    return redirect(url_for("property_detail", property_id=property_id))


@app.route("/timeline")
def timeline():
    """Show full compliance timeline."""
    db = get_db()
    tl = TimelineGenerator(db)

    # Get filter parameters
    days = int(request.args.get("days", 90))
    property_id = request.args.get("property_id", type=int)

    overdue = tl.get_overdue_events(property_id=property_id)
    upcoming = tl.get_upcoming_events(days=days, property_id=property_id)

    # Remove overdue from upcoming
    overdue_ids = {e.id for e in overdue}
    upcoming = [e for e in upcoming if e.id not in overdue_ids]

    # Get all properties for filter dropdown
    properties = db.list_properties()

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
def complete_event(event_id: int):
    """Mark an event as completed."""
    db = get_db()
    tl = TimelineGenerator(db)
    tl.mark_complete(event_id)
    flash("Event marked as completed", "success")

    # Redirect back to referring page
    return redirect(request.referrer or url_for("timeline"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
