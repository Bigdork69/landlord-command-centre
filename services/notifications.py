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


@dataclass
class EmailSettings:
    """Email configuration settings."""
    enabled: bool = False
    recipient_email: str = ""


class NotificationService:
    """Service for sending expiry reminder notifications."""

    def __init__(self, db: Database):
        self.db = db
        self._ensure_tables()

    def _ensure_tables(self) -> None:
        """Ensure notification tables exist."""
        with self.db.connection() as conn:
            conn.executescript("""
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
            """)

    def get_email_settings(self) -> EmailSettings:
        """Get current email settings."""
        with self.db.connection() as conn:
            cursor = conn.execute("SELECT enabled, recipient_email FROM email_settings WHERE id = 1")
            row = cursor.fetchone()
            if row:
                return EmailSettings(
                    enabled=bool(row["enabled"]),
                    recipient_email=row["recipient_email"] or "",
                )
            return EmailSettings()

    def save_email_settings(self, settings: EmailSettings) -> None:
        """Save email settings."""
        with self.db.connection() as conn:
            conn.execute("""
                INSERT INTO email_settings (id, enabled, recipient_email)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    enabled = excluded.enabled,
                    recipient_email = excluded.recipient_email
            """, (
                settings.enabled,
                settings.recipient_email,
            ))

    def get_expiring_items(self) -> list[ExpiryItem]:
        """Get all items that need reminders based on the schedule."""
        today = date.today()
        items = []

        # Check certificates
        for cert_type in CertificateType:
            items.extend(self._get_expiring_certificates(cert_type, today))

        # Check compliance events with due dates
        items.extend(self._get_expiring_events(today))

        return items

    def _get_expiring_certificates(self, cert_type: CertificateType, today: date) -> list[ExpiryItem]:
        """Get certificates of a type that are expiring within the reminder window."""
        items = []
        properties = self.db.list_properties()

        cert_names = {
            CertificateType.GAS_SAFETY: "Gas Safety Certificate",
            CertificateType.EICR: "EICR (Electrical)",
            CertificateType.EPC: "EPC",
            CertificateType.FIRE_SAFETY: "Fire Safety Certificate",
        }

        for prop in properties:
            cert = self.db.get_latest_certificate(prop.id, cert_type)
            if cert and cert.expiry_date:
                days_until = (cert.expiry_date - today).days

                # Check each reminder threshold
                for label, days in REMINDER_SCHEDULE:
                    if days_until <= days and days_until > 0:
                        # Check if already sent
                        if not self._reminder_already_sent("certificate", cert.id, days):
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

    def _get_expiring_events(self, today: date) -> list[ExpiryItem]:
        """Get compliance events that are due within the reminder window."""
        items = []
        properties = self.db.list_properties()

        for prop in properties:
            events = self.db.list_events(property_id=prop.id)
            for event in events:
                if event.due_date and event.status.value == "pending":
                    days_until = (event.due_date - today).days

                    # Check each reminder threshold
                    for label, days in REMINDER_SCHEDULE:
                        if days_until <= days and days_until > 0:
                            # Check if already sent
                            if not self._reminder_already_sent("event", event.id, days):
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

    def _reminder_already_sent(self, item_type: str, item_id: int, reminder_days: int) -> bool:
        """Check if a reminder has already been sent for this item/threshold."""
        with self.db.connection() as conn:
            cursor = conn.execute(
                "SELECT 1 FROM sent_reminders WHERE item_type = ? AND item_id = ? AND reminder_days = ?",
                (item_type, item_id, reminder_days),
            )
            return cursor.fetchone() is not None

    def _mark_reminder_sent(self, item_type: str, item_id: int, reminder_days: int) -> None:
        """Mark a reminder as sent."""
        with self.db.connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sent_reminders (item_type, item_id, reminder_days, sent_date) VALUES (?, ?, ?, ?)",
                (item_type, item_id, reminder_days, date.today().isoformat()),
            )

    def send_reminders(self) -> dict:
        """Check for expiring items and send reminder emails. Returns summary."""
        settings = self.get_email_settings()

        if not settings.enabled:
            return {"status": "disabled", "sent": 0, "items": []}

        if not settings.recipient_email:
            return {"status": "error", "message": "No recipient email configured", "sent": 0}

        items = self.get_expiring_items()

        if not items:
            return {"status": "ok", "sent": 0, "message": "No reminders needed"}

        # Group items by reminder urgency
        grouped = {}
        for item in items:
            if item.reminder_label not in grouped:
                grouped[item.reminder_label] = []
            grouped[item.reminder_label].append(item)

        # Build email
        subject = f"Landlord Compliance Reminders - {len(items)} item(s) expiring"
        body = self._build_email_body(grouped)

        try:
            self._send_email(settings.recipient_email, subject, body)

            # Mark all as sent
            for item in items:
                for label, days in REMINDER_SCHEDULE:
                    if label == item.reminder_label:
                        self._mark_reminder_sent(item.item_type, item.item_id, days)
                        break

            return {
                "status": "ok",
                "sent": len(items),
                "items": [{"name": i.name, "property": i.property_address, "expires": str(i.expiry_date)} for i in items],
            }

        except Exception as e:
            return {"status": "error", "message": str(e), "sent": 0}

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

    def get_pending_reminders_preview(self) -> list[ExpiryItem]:
        """Get items that would trigger reminders (for preview/testing)."""
        return self.get_expiring_items()

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
