"""Email notification service for expiry reminders."""

import json
import ssl
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import date
from typing import Optional

import certifi

from config import get_config
from database import Database
from models import CertificateType


# Reminder schedule: days before expiry
REMINDER_SCHEDULE = [
    ("3 months", 90),
    ("2 months", 60),
    ("4 weeks", 28),
    ("3 weeks", 21),
    ("2 weeks", 14),
    ("1 week", 7),
]


@dataclass
class ExpiryItem:
    """An item that is expiring and needs a reminder."""
    item_type: str  # 'certificate' or 'event'
    item_id: int
    name: str
    property_address: str
    expiry_date: date
    days_until_expiry: int
    reminder_label: str  # e.g., "3 months", "2 weeks"


class NotificationService:
    """Service for sending expiry reminder notifications."""

    def __init__(self, db: Database):
        self.db = db
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Ensure notification tables exist."""
        with self.db.connection() as conn:
            if self.db.use_postgres:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sent_reminders (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL,
                        item_type TEXT NOT NULL,
                        item_id INTEGER NOT NULL,
                        reminder_days INTEGER NOT NULL,
                        sent_date DATE NOT NULL,
                        UNIQUE(user_id, item_type, item_id, reminder_days)
                    )
                """)
            else:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sent_reminders (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER NOT NULL,
                        item_type TEXT NOT NULL,
                        item_id INTEGER NOT NULL,
                        reminder_days INTEGER NOT NULL,
                        sent_date DATE NOT NULL,
                        UNIQUE(user_id, item_type, item_id, reminder_days)
                    )
                """)

    def get_expiring_items(self, user_id: Optional[int] = None) -> list[ExpiryItem]:
        """Get all items that need reminders based on the schedule."""
        today = date.today()
        items = []

        # Check certificates
        for cert_type in CertificateType:
            items.extend(self._get_expiring_certificates(cert_type, today, user_id))

        # Check compliance events with due dates
        items.extend(self._get_expiring_events(today, user_id))

        return items

    def _get_expiring_certificates(self, cert_type: CertificateType, today: date, user_id: Optional[int] = None) -> list[ExpiryItem]:
        """Get certificates of a type that are expiring within the reminder window."""
        items = []
        # If user_id provided, filter to that user's properties
        if user_id is not None:
            properties = self.db.list_properties(user_id=user_id)
        else:
            # Fallback for system-wide reminders (no user_id means check all)
            properties = self._list_all_properties()

        cert_names = {
            CertificateType.GAS_SAFETY: "Gas Safety Certificate",
            CertificateType.EICR: "EICR (Electrical)",
            CertificateType.EPC: "EPC",
            CertificateType.FIRE_SAFETY: "Fire Safety Certificate",
        }

        for prop in properties:
            if user_id is not None:
                cert = self.db.get_latest_certificate(prop.id, cert_type, user_id=user_id)
            else:
                cert = self._get_latest_certificate_any_user(prop.id, cert_type)
            if cert and cert.expiry_date:
                days_until = (cert.expiry_date - today).days

                # Check each reminder threshold
                for label, days in REMINDER_SCHEDULE:
                    if days_until <= days and days_until > 0:
                        # Check if already sent (user_id required for tracking)
                        if user_id is not None and not self._reminder_already_sent("certificate", cert.id, days, user_id):
                            items.append(ExpiryItem(
                                item_type="certificate",
                                item_id=cert.id,
                                name=cert_names.get(cert_type, cert_type.value),
                                property_address=f"{prop.address}, {prop.postcode}",
                                expiry_date=cert.expiry_date,
                                days_until_expiry=days_until,
                                reminder_label=label,
                            ))
                        break  # Only add one reminder per item

        return items

    def _get_expiring_events(self, today: date, user_id: Optional[int] = None) -> list[ExpiryItem]:
        """Get compliance events that are due within the reminder window."""
        items = []
        # If user_id provided, filter to that user's properties
        if user_id is not None:
            properties = self.db.list_properties(user_id=user_id)
        else:
            properties = self._list_all_properties()

        for prop in properties:
            if user_id is not None:
                events = self.db.list_events(user_id=user_id, property_id=prop.id)
            else:
                events = self._list_events_any_user(property_id=prop.id)
            for event in events:
                if event.due_date and event.status.value == "pending":
                    days_until = (event.due_date - today).days

                    # Check each reminder threshold
                    for label, days in REMINDER_SCHEDULE:
                        if days_until <= days and days_until > 0:
                            # Check if already sent (user_id required for tracking)
                            if user_id is not None and not self._reminder_already_sent("event", event.id, days, user_id):
                                items.append(ExpiryItem(
                                    item_type="event",
                                    item_id=event.id,
                                    name=event.event_name,
                                    property_address=f"{prop.address}, {prop.postcode}",
                                    expiry_date=event.due_date,
                                    days_until_expiry=days_until,
                                    reminder_label=label,
                                ))
                            break  # Only add one reminder per item

        return items

    def _list_all_properties(self) -> list:
        """List all properties across all users (for system-wide reminders)."""
        from models import Property, PropertyType
        with self.db.connection() as conn:
            cursor = conn.execute("SELECT * FROM properties ORDER BY address")
            rows = cursor.fetchall()
            return [
                Property(
                    id=row["id"],
                    address=row["address"],
                    postcode=row["postcode"],
                    property_type=PropertyType(row["property_type"]),
                )
                for row in rows
            ]

    def _get_latest_certificate_any_user(self, property_id: int, cert_type: CertificateType):
        """Get the most recent certificate of a type for a property (any user)."""
        from models import Certificate
        with self.db.connection() as conn:
            cursor = conn.execute(
                """SELECT * FROM certificates
                   WHERE property_id = ? AND certificate_type = ?
                   ORDER BY issue_date DESC LIMIT 1""",
                (property_id, cert_type.value),
            )
            row = cursor.fetchone()
            if row:
                return Certificate(
                    id=row["id"],
                    property_id=row["property_id"],
                    certificate_type=CertificateType(row["certificate_type"]),
                    issue_date=self.db._parse_date(row["issue_date"]),
                    expiry_date=self.db._parse_date(row["expiry_date"]),
                    document_path=row["document_path"] or "",
                    served_to_tenant_date=self.db._parse_date(row["served_to_tenant_date"]),
                    reference_number=row["reference_number"] or "",
                    notes=row["notes"] or "",
                )
            return None

    def _list_events_any_user(self, property_id: int) -> list:
        """List compliance events for a property (any user)."""
        from models import ComplianceEvent, EventStatus, EventPriority
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM compliance_events WHERE property_id = ? ORDER BY due_date ASC",
                (property_id,),
            )
            return [
                ComplianceEvent(
                    id=row["id"],
                    property_id=row["property_id"],
                    tenancy_id=row["tenancy_id"],
                    event_type=row["event_type"],
                    event_name=row["event_name"],
                    due_date=self.db._parse_date(row["due_date"]),
                    completed_date=self.db._parse_date(row["completed_date"]),
                    status=EventStatus(row["status"]),
                    priority=EventPriority(row["priority"]),
                    notes=row["notes"] or "",
                )
                for row in cursor.fetchall()
            ]

    def _reminder_already_sent(self, item_type: str, item_id: int, reminder_days: int, user_id: int) -> bool:
        """Check if a reminder has already been sent for this item/threshold for this user."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM sent_reminders WHERE user_id = ? AND item_type = ? AND item_id = ? AND reminder_days = ?",
                (user_id, item_type, item_id, reminder_days),
            )
            return cursor.fetchone() is not None

    def _mark_reminder_sent(self, item_type: str, item_id: int, reminder_days: int, user_id: int) -> None:
        """Mark a reminder as sent for a user."""
        with self.db.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sent_reminders (user_id, item_type, item_id, reminder_days, sent_date) VALUES (?, ?, ?, ?, ?)",
                (user_id, item_type, item_id, reminder_days, date.today().isoformat()),
            )

    def _group_items(self, items: list[ExpiryItem]) -> dict:
        """Group items by reminder urgency."""
        grouped = {}
        for item in items:
            if item.reminder_label not in grouped:
                grouped[item.reminder_label] = []
            grouped[item.reminder_label].append(item)
        return grouped

    def send_reminders(self, user_id: int, user_email: str) -> dict:
        """Send reminders for a specific user. Returns summary."""
        items = self.get_expiring_items(user_id=user_id)

        if not items:
            return {"status": "ok", "sent": 0, "message": "No reminders needed"}

        # Group items by reminder urgency
        grouped = self._group_items(items)

        # Build email
        subject = f"Landlord Compliance Reminders - {len(items)} item(s) expiring"
        body = self._build_email_body(grouped)

        try:
            self._send_email(user_email, subject, body)

            # Mark all as sent
            for item in items:
                for label, days in REMINDER_SCHEDULE:
                    if label == item.reminder_label:
                        self._mark_reminder_sent(item.item_type, item.item_id, days, user_id)
                        break

            return {
                "status": "ok",
                "sent": len(items),
                "items": [{"name": i.name, "property": i.property_address, "expires": str(i.expiry_date)} for i in items],
            }

        except Exception as e:
            return {"status": "error", "message": str(e), "sent": 0}

    def send_reminders_for_all_users(self) -> dict:
        """Check all users and send reminders. Called by cron job or admin."""
        results = []

        # Get all active users
        with self.db.connection() as conn:
            cursor = conn.execute("SELECT id, email, name FROM users WHERE is_active = 1")
            users = cursor.fetchall()

        for user in users:
            user_id = user["id"]
            email = user["email"]

            result = self.send_reminders(user_id, email)
            results.append({"user": email, **result})

        return {"status": "ok", "results": results}

    def _build_email_body(self, grouped: dict) -> str:
        """Build the email body with grouped reminders."""
        lines = [
            "LANDLORD COMMAND CENTRE - COMPLIANCE REMINDERS",
            "=" * 50,
            "",
        ]

        # Order by urgency (most urgent first)
        urgency_order = ["1 week", "2 weeks", "3 weeks", "4 weeks", "2 months", "3 months"]

        for label in urgency_order:
            if label in grouped:
                items = grouped[label]
                lines.append(f"EXPIRING IN {label.upper()} ({len(items)} item(s))")
                lines.append("-" * 40)

                for item in items:
                    lines.append(f"  - {item.name}")
                    lines.append(f"    Property: {item.property_address}")
                    lines.append(f"    Expires: {item.expiry_date.strftime('%d %B %Y')} ({item.days_until_expiry} days)")
                    lines.append("")

                lines.append("")

        lines.extend([
            "---",
            "Log in to Landlord Command Centre to take action.",
            "",
            "This is an automated reminder. Do not reply to this email.",
        ])

        return "\n".join(lines)

    def _send_email(self, recipient_email: str, subject: str, body: str) -> None:
        """Send an email using Resend API."""
        config = get_config()
        if not config.resend_api_key:
            raise ValueError("RESEND_API_KEY not configured in environment")

        data = json.dumps({
            "from": "Landlord Command Centre <reminders@resend.dev>",
            "to": [recipient_email],
            "subject": subject,
            "text": body,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=data,
            headers={
                "Authorization": f"Bearer {config.resend_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as response:
                if response.status not in (200, 201):
                    raise ValueError(f"Resend API error: {response.status}")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise ValueError(f"Failed to send email: {error_body}")

    def get_pending_reminders_preview(self, user_id: Optional[int] = None) -> list[ExpiryItem]:
        """Get items that would trigger reminders (for preview/testing)."""
        return self.get_expiring_items(user_id=user_id)

    def clear_sent_reminders(self, item_type: Optional[str] = None, item_id: Optional[int] = None) -> None:
        """Clear sent reminder records (useful for testing or resetting)."""
        with self.db.connection() as conn:
            if item_type and item_id:
                conn.execute(
                    "DELETE FROM sent_reminders WHERE item_type = ? AND item_id = ?",
                    (item_type, item_id),
                )
            elif item_type:
                conn.execute("DELETE FROM sent_reminders WHERE item_type = ?", (item_type,))
            else:
                conn.execute("DELETE FROM sent_reminders")
