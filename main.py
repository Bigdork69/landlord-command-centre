"""Landlord Command Centre - CLI for UK property compliance management."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

import click
import typer
from rich.console import Console
from rich.table import Table

from config import get_config
from database import Database
from models import Property, PropertyType, RentFrequency, Tenancy

app = typer.Typer(
    name="landlord",
    help="CLI tool for UK landlords to manage property compliance.",
    no_args_is_help=True,
)
property_app = typer.Typer(help="Manage properties")
tenancy_app = typer.Typer(help="Manage tenancies")
app.add_typer(property_app, name="property")
app.add_typer(tenancy_app, name="tenancy")

console = Console()


def get_db() -> Database:
    """Get database instance."""
    config = get_config()
    return Database(config.database_path)


@app.command()
def init():
    """Initialize the database and configuration."""
    config = get_config()
    config.ensure_directories()
    db = get_db()
    db.initialize()
    console.print(f"[green]Database initialized at {config.database_path}[/green]")


# Property commands


@property_app.command("add")
def property_add(
    address: Optional[str] = typer.Option(None, "--address", "-a", help="Property address"),
    postcode: Optional[str] = typer.Option(None, "--postcode", "-p", help="Property postcode"),
    property_type: Optional[str] = typer.Option(
        None, "--type", "-t", help="Property type (house, flat, maisonette, studio, room, other)"
    ),
):
    """Add a new property."""
    # Interactive prompts if not provided
    if not address:
        address = typer.prompt("Property address")
    if not postcode:
        postcode = typer.prompt("Postcode")
    if not property_type:
        property_type = typer.prompt(
            "Property type",
            default="house",
            show_choices=True,
            type=click.Choice(["house", "flat", "maisonette", "studio", "room", "other"]),
        )

    prop = Property(
        address=address,
        postcode=postcode.upper(),
        property_type=PropertyType(property_type),
    )

    db = get_db()
    prop_id = db.create_property(prop)
    console.print(f"[green]Property created with ID: {prop_id}[/green]")


@property_app.command("list")
def property_list():
    """List all properties."""
    db = get_db()
    properties = db.list_properties()

    if not properties:
        console.print("[yellow]No properties found. Add one with 'landlord property add'[/yellow]")
        return

    table = Table(title="Properties")
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Address", style="white")
    table.add_column("Postcode", style="white")
    table.add_column("Type", style="white")

    for prop in properties:
        table.add_row(
            str(prop.id),
            prop.address,
            prop.postcode,
            prop.property_type.value,
        )

    console.print(table)


@property_app.command("show")
def property_show(property_id: int = typer.Argument(..., help="Property ID")):
    """Show details for a property."""
    db = get_db()
    prop = db.get_property(property_id)

    if not prop:
        console.print(f"[red]Property {property_id} not found[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Property #{prop.id}[/bold]")
    console.print(f"  Address: {prop.address}")
    console.print(f"  Postcode: {prop.postcode}")
    console.print(f"  Type: {prop.property_type.value}")
    console.print(f"  Created: {prop.created_at.strftime('%Y-%m-%d')}")

    # Show tenancies
    tenancies = db.list_tenancies_for_property(property_id)
    if tenancies:
        console.print(f"\n[bold]Tenancies ({len(tenancies)}):[/bold]")
        for t in tenancies:
            status = "[green]Active[/green]" if t.is_active else "[dim]Ended[/dim]"
            console.print(f"  #{t.id}: {t.tenant_names} - {status}")


# Tenancy commands


@tenancy_app.command("add")
def tenancy_add(
    property_id: int = typer.Argument(..., help="Property ID for this tenancy"),
):
    """Add a new tenancy to a property."""
    db = get_db()
    prop = db.get_property(property_id)

    if not prop:
        console.print(f"[red]Property {property_id} not found[/red]")
        raise typer.Exit(1)

    console.print(f"\n[bold]Adding tenancy to: {prop.address}[/bold]\n")

    # Collect tenancy details
    tenant_names = typer.prompt("Tenant name(s)")

    start_date_str = typer.prompt("Tenancy start date (YYYY-MM-DD)")
    try:
        start_date = date.fromisoformat(start_date_str)
    except ValueError:
        console.print("[red]Invalid date format. Use YYYY-MM-DD[/red]")
        raise typer.Exit(1)

    end_date_str = typer.prompt("Fixed term end date (YYYY-MM-DD, or leave blank for periodic)", default="")
    end_date = None
    if end_date_str:
        try:
            end_date = date.fromisoformat(end_date_str)
        except ValueError:
            console.print("[red]Invalid date format. Use YYYY-MM-DD[/red]")
            raise typer.Exit(1)

    rent_str = typer.prompt("Rent amount (£)")
    try:
        rent_amount = Decimal(rent_str.replace(",", "").replace("£", ""))
    except Exception:
        console.print("[red]Invalid rent amount[/red]")
        raise typer.Exit(1)

    rent_frequency = typer.prompt(
        "Rent frequency",
        default="monthly",
        show_choices=True,
        type=click.Choice(["weekly", "fortnightly", "monthly", "quarterly", "annually"]),
    )

    deposit_str = typer.prompt("Deposit amount (£)", default="0")
    try:
        deposit_amount = Decimal(deposit_str.replace(",", "").replace("£", ""))
    except Exception:
        console.print("[red]Invalid deposit amount[/red]")
        raise typer.Exit(1)

    tenancy = Tenancy(
        property_id=property_id,
        tenant_names=tenant_names,
        tenancy_start_date=start_date,
        fixed_term_end_date=end_date,
        rent_amount=rent_amount,
        rent_frequency=RentFrequency(rent_frequency),
        deposit_amount=deposit_amount,
    )

    tenancy_id = db.create_tenancy(tenancy)
    console.print(f"\n[green]Tenancy created with ID: {tenancy_id}[/green]")

    # Generate compliance timeline
    from services.timeline import TimelineGenerator
    generator = TimelineGenerator(db)
    events = generator.generate_for_tenancy(db.get_tenancy(tenancy_id))
    console.print(f"[green]Generated {len(events)} compliance events[/green]")


@tenancy_app.command("list")
def tenancy_list(
    active: bool = typer.Option(False, "--active", "-a", help="Show only active tenancies"),
):
    """List all tenancies."""
    db = get_db()
    tenancies = db.list_tenancies(active_only=active)

    if not tenancies:
        console.print("[yellow]No tenancies found[/yellow]")
        return

    table = Table(title="Tenancies")
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("Property", style="white")
    table.add_column("Tenant(s)", style="white")
    table.add_column("Start Date", style="white")
    table.add_column("Rent", style="white")
    table.add_column("Status", style="white")

    for t in tenancies:
        prop = db.get_property(t.property_id)
        prop_str = prop.address[:30] if prop else f"#{t.property_id}"
        status = "[green]Active[/green]" if t.is_active else "[dim]Ended[/dim]"
        table.add_row(
            str(t.id),
            prop_str,
            t.tenant_names[:25],
            t.tenancy_start_date.strftime("%Y-%m-%d") if t.tenancy_start_date else "-",
            f"£{t.rent_amount:,.2f}/{t.rent_frequency.value[:3]}",
            status,
        )

    console.print(table)


@tenancy_app.command("show")
def tenancy_show(tenancy_id: int = typer.Argument(..., help="Tenancy ID")):
    """Show detailed tenancy information."""
    db = get_db()
    tenancy = db.get_tenancy(tenancy_id)

    if not tenancy:
        console.print(f"[red]Tenancy {tenancy_id} not found[/red]")
        raise typer.Exit(1)

    prop = db.get_property(tenancy.property_id)

    console.print(f"\n[bold]Tenancy #{tenancy.id}[/bold]")
    console.print(f"  Property: {prop.address if prop else 'Unknown'}, {prop.postcode if prop else ''}")
    console.print(f"  Tenant(s): {tenancy.tenant_names}")
    console.print(f"  Status: {'[green]Active[/green]' if tenancy.is_active else '[dim]Ended[/dim]'}")

    console.print(f"\n[bold]Dates[/bold]")
    console.print(f"  Start: {tenancy.tenancy_start_date}")
    console.print(f"  Fixed term end: {tenancy.fixed_term_end_date or 'Periodic'}")
    console.print(f"  Type: {'Periodic' if tenancy.is_periodic else 'Fixed term'}")

    console.print(f"\n[bold]Rent & Deposit[/bold]")
    console.print(f"  Rent: £{tenancy.rent_amount:,.2f} {tenancy.rent_frequency.value}")
    console.print(f"  Weekly equivalent: £{tenancy.weekly_rent:,.2f}")
    console.print(f"  Deposit: £{tenancy.deposit_amount:,.2f}")

    console.print(f"\n[bold]Compliance Status[/bold]")
    deposit_status = "[green]Yes[/green]" if tenancy.deposit_protected else "[red]No[/red]"
    console.print(f"  Deposit protected: {deposit_status}")
    if tenancy.deposit_protection_date:
        console.print(f"  Protected on: {tenancy.deposit_protection_date}")
    if tenancy.deposit_scheme:
        console.print(f"  Scheme: {tenancy.deposit_scheme}")

    pi_status = "[green]Yes[/green]" if tenancy.prescribed_info_served else "[red]No[/red]"
    console.print(f"  Prescribed info served: {pi_status}")

    htr_status = "[green]Yes[/green]" if tenancy.how_to_rent_served else "[red]No[/red]"
    console.print(f"  How to Rent served: {htr_status}")

    if tenancy.document_path:
        console.print(f"\n  Source document: {tenancy.document_path}")


if __name__ == "__main__":
    app()
