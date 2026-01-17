"""Flask web interface for Landlord Command Centre."""

import os
from datetime import date
from decimal import Decimal

from flask import Flask, flash, redirect, render_template, request, url_for

from config import get_config
from database import Database
from models import Property, PropertyType, RentFrequency, Tenancy

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-prod")


def get_db() -> Database:
    """Get database instance."""
    config = get_config()
    config.ensure_directories()
    db = Database(config.database_path)
    db.initialize()
    return db


@app.route("/")
def index():
    """Dashboard showing overview."""
    db = get_db()
    properties = db.list_properties()
    tenancies = db.list_tenancies(active_only=True)

    # Calculate some stats
    total_rent = sum(t.rent_amount for t in tenancies)

    return render_template(
        "index.html",
        properties=properties,
        tenancies=tenancies,
        total_rent=total_rent,
        property_count=len(properties),
        tenancy_count=len(tenancies),
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

    # Attach property info to each tenancy
    tenancies_with_props = []
    for t in tenancy_list:
        prop = db.get_property(t.property_id)
        tenancies_with_props.append({"tenancy": t, "property": prop})

    return render_template("tenancies.html", tenancies=tenancies_with_props)


@app.route("/tenancies/add", methods=["GET", "POST"])
def add_tenancy():
    """Add a new tenancy."""
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
            flash(f"Tenancy created with ID: {tenancy_id}", "success")
            return redirect(url_for("tenancy_detail", tenancy_id=tenancy_id))
        except Exception as e:
            flash(f"Error creating tenancy: {e}", "error")

    properties = db.list_properties()
    return render_template(
        "add_tenancy.html",
        properties=properties,
        rent_frequencies=RentFrequency,
    )


@app.route("/tenancies/<int:tenancy_id>")
def tenancy_detail(tenancy_id: int):
    """Show tenancy details."""
    db = get_db()
    tenancy = db.get_tenancy(tenancy_id)
    if not tenancy:
        flash("Tenancy not found", "error")
        return redirect(url_for("tenancies"))

    prop = db.get_property(tenancy.property_id)
    return render_template("tenancy_detail.html", tenancy=tenancy, property=prop)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
