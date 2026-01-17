"""Flask web interface for Landlord Command Centre."""

import os
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from config import get_config
from database import Database
from models import EventPriority, EventStatus, Property, PropertyType, RentFrequency, Tenancy
from parsers.tenancy import TenancyParser
from services.timeline import TimelineGenerator

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-prod")

# File upload config
UPLOAD_FOLDER = Path(__file__).parent / "uploads"
ALLOWED_EXTENSIONS = {"pdf"}
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
    """Show property details."""
    db = get_db()
    prop = db.get_property(property_id)
    if not prop:
        flash("Property not found", "error")
        return redirect(url_for("properties"))

    tenancies = db.list_tenancies_for_property(property_id)
    return render_template("property_detail.html", property=prop, tenancies=tenancies)


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
