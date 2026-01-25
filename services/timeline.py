"""Compliance timeline generator with UK landlord regulations."""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Optional

from database import Database
from models import (
    CertificateType,
    ComplianceEvent,
    EventPriority,
    EventStatus,
    Tenancy,
)


@dataclass
class ComplianceRule:
    """A compliance rule that generates events."""
    event_type: str
    event_name: str
    calculate_due_date: Callable[[Tenancy, Optional[date]], Optional[date]]
    priority: EventPriority
    description: str
    recurring_days: Optional[int] = None  # If set, event recurs every N days


class TimelineGenerator:
    """Generate compliance timeline events for tenancies."""

    def __init__(self, db: Database, user_id: int):
        self.db = db
        self.user_id = user_id
        self.rules = self._create_rules()

    def _create_rules(self) -> list[ComplianceRule]:
        """Create all compliance rules based on UK regulations."""
        return [
            # === CRITICAL (within 30 days of tenancy start) ===
            ComplianceRule(
                event_type="deposit_protection",
                event_name="Protect deposit in government scheme",
                calculate_due_date=lambda t, _: t.tenancy_start_date + timedelta(days=30) if t.tenancy_start_date and t.deposit_amount > 0 else None,
                priority=EventPriority.CRITICAL,
                description="Deposit must be protected within 30 days of receipt. Failure can result in 1-3x deposit penalty.",
            ),
            ComplianceRule(
                event_type="prescribed_info",
                event_name="Serve prescribed information to tenant",
                calculate_due_date=lambda t, _: t.tenancy_start_date + timedelta(days=30) if t.tenancy_start_date and t.deposit_amount > 0 else None,
                priority=EventPriority.CRITICAL,
                description="Prescribed information about deposit protection must be given within 30 days.",
            ),
            ComplianceRule(
                event_type="gas_safety_serve",
                event_name="Give Gas Safety Certificate to tenant",
                calculate_due_date=lambda t, _: t.tenancy_start_date if t.tenancy_start_date else None,
                priority=EventPriority.CRITICAL,
                description="Gas Safety Certificate must be given to tenant before they move in.",
            ),

            # === HIGH PRIORITY (at or near tenancy start) ===
            ComplianceRule(
                event_type="eicr_serve",
                event_name="Give EICR to tenant",
                calculate_due_date=lambda t, _: t.tenancy_start_date + timedelta(days=28) if t.tenancy_start_date else None,
                priority=EventPriority.HIGH,
                description="EICR must be given to tenant within 28 days of tenancy start.",
            ),
            ComplianceRule(
                event_type="epc_serve",
                event_name="Give EPC to tenant",
                calculate_due_date=lambda t, _: t.tenancy_start_date if t.tenancy_start_date else None,
                priority=EventPriority.HIGH,
                description="EPC must be available to prospective tenants and given at tenancy start.",
            ),
            ComplianceRule(
                event_type="how_to_rent",
                event_name="Serve 'How to Rent' guide",
                calculate_due_date=lambda t, _: t.tenancy_start_date if t.tenancy_start_date else None,
                priority=EventPriority.HIGH,
                description="How to Rent guide must be given to tenant at start of tenancy.",
            ),
            ComplianceRule(
                event_type="smoke_co_alarms",
                event_name="Test smoke and CO alarms",
                calculate_due_date=lambda t, _: t.tenancy_start_date if t.tenancy_start_date else None,
                priority=EventPriority.HIGH,
                description="Smoke alarms on every floor and CO alarms in rooms with fixed combustion appliances. Must be tested at start of tenancy.",
            ),

            # === RECURRING CERTIFICATES ===
            ComplianceRule(
                event_type="gas_safety_renewal",
                event_name="Renew Gas Safety Certificate",
                calculate_due_date=self._gas_safety_due_date,
                priority=EventPriority.CRITICAL,
                description="Gas Safety Certificate expires annually. Must be renewed before expiry.",
                recurring_days=365,
            ),
            ComplianceRule(
                event_type="eicr_renewal",
                event_name="Renew EICR (Electrical Safety)",
                calculate_due_date=self._eicr_due_date,
                priority=EventPriority.HIGH,
                description="EICR expires every 5 years (or as specified on certificate). Must be renewed before expiry.",
                recurring_days=365 * 5,
            ),
            ComplianceRule(
                event_type="epc_renewal",
                event_name="Renew EPC",
                calculate_due_date=self._epc_due_date,
                priority=EventPriority.MEDIUM,
                description="EPC expires every 10 years. Property must have valid EPC rated E or above.",
                recurring_days=365 * 10,
            ),

            # === RENTERS' RIGHTS ACT 2025 ===
            ComplianceRule(
                event_type="rent_increase_earliest",
                event_name="Earliest rent increase date",
                calculate_due_date=lambda t, _: t.tenancy_start_date + timedelta(days=365) if t.tenancy_start_date else None,
                priority=EventPriority.MEDIUM,
                description="Under Renters' Rights Act 2025, rent can only be increased once per year, minimum 12 months after tenancy start.",
            ),

            # === MEDIUM PRIORITY ===
            ComplianceRule(
                event_type="right_to_rent",
                event_name="Verify Right to Rent",
                calculate_due_date=lambda t, _: t.tenancy_start_date if t.tenancy_start_date else None,
                priority=EventPriority.MEDIUM,
                description="Landlord must check tenant has right to rent in England before tenancy starts.",
            ),
            ComplianceRule(
                event_type="legionella_assessment",
                event_name="Legionella risk assessment",
                calculate_due_date=lambda t, _: t.tenancy_start_date if t.tenancy_start_date else None,
                priority=EventPriority.LOW,
                description="Landlords should assess risk of Legionella exposure. Not legally required but recommended.",
            ),
        ]

    def _gas_safety_due_date(self, tenancy: Tenancy, last_date: Optional[date]) -> Optional[date]:
        """Calculate Gas Safety renewal due date."""
        # Check for existing certificate
        cert = self.db.get_latest_certificate(tenancy.property_id, CertificateType.GAS_SAFETY, user_id=self.user_id)
        if cert and cert.expiry_date:
            return cert.expiry_date
        # If no certificate, due from tenancy start + 1 year
        if tenancy.tenancy_start_date:
            return tenancy.tenancy_start_date + timedelta(days=365)
        return None

    def _eicr_due_date(self, tenancy: Tenancy, last_date: Optional[date]) -> Optional[date]:
        """Calculate EICR renewal due date."""
        cert = self.db.get_latest_certificate(tenancy.property_id, CertificateType.EICR, user_id=self.user_id)
        if cert and cert.expiry_date:
            return cert.expiry_date
        # If no certificate, due from tenancy start + 5 years
        if tenancy.tenancy_start_date:
            return tenancy.tenancy_start_date + timedelta(days=365 * 5)
        return None

    def _epc_due_date(self, tenancy: Tenancy, last_date: Optional[date]) -> Optional[date]:
        """Calculate EPC renewal due date."""
        cert = self.db.get_latest_certificate(tenancy.property_id, CertificateType.EPC, user_id=self.user_id)
        if cert and cert.expiry_date:
            return cert.expiry_date
        # If no certificate, assume needed now
        if tenancy.tenancy_start_date:
            return tenancy.tenancy_start_date
        return None

    def generate_for_tenancy(self, tenancy: Tenancy) -> list[ComplianceEvent]:
        """Generate all compliance events for a tenancy."""
        if not tenancy or not tenancy.id:
            return []

        # Delete existing events for this tenancy to regenerate
        self.db.delete_events_for_tenancy(tenancy.id, user_id=self.user_id)

        events = []
        today = date.today()

        for rule in self.rules:
            due_date = rule.calculate_due_date(tenancy, None)

            if due_date is None:
                continue

            # Determine status
            if due_date < today:
                status = EventStatus.OVERDUE
            else:
                status = EventStatus.PENDING

            event = ComplianceEvent(
                property_id=tenancy.property_id,
                tenancy_id=tenancy.id,
                event_type=rule.event_type,
                event_name=rule.event_name,
                due_date=due_date,
                status=status,
                priority=rule.priority,
                notes=rule.description,
            )

            event_id = self.db.create_event(event, user_id=self.user_id)
            event.id = event_id
            events.append(event)

        return events

    def get_upcoming_events(
        self,
        days: int = 30,
        property_id: Optional[int] = None,
        tenancy_id: Optional[int] = None,
    ) -> list[ComplianceEvent]:
        """Get events due within the specified number of days."""
        all_events = self.db.list_events(
            user_id=self.user_id,
            property_id=property_id,
            tenancy_id=tenancy_id,
        )

        today = date.today()
        cutoff = today + timedelta(days=days)

        upcoming = []
        for event in all_events:
            if event.status == EventStatus.COMPLETED:
                continue
            if event.due_date and event.due_date <= cutoff:
                # Update status if overdue
                if event.due_date < today and event.status != EventStatus.OVERDUE:
                    self.db.update_event_status(event.id, self.user_id, EventStatus.OVERDUE)
                    event.status = EventStatus.OVERDUE
                upcoming.append(event)

        # Sort by due date, then priority
        priority_order = {
            EventPriority.CRITICAL: 0,
            EventPriority.HIGH: 1,
            EventPriority.MEDIUM: 2,
            EventPriority.LOW: 3,
        }
        upcoming.sort(key=lambda e: (e.due_date or date.max, priority_order.get(e.priority, 99)))

        return upcoming

    def get_overdue_events(
        self,
        property_id: Optional[int] = None,
        tenancy_id: Optional[int] = None,
    ) -> list[ComplianceEvent]:
        """Get all overdue events."""
        all_events = self.db.list_events(
            user_id=self.user_id,
            property_id=property_id,
            tenancy_id=tenancy_id,
        )

        today = date.today()
        overdue = []

        for event in all_events:
            if event.status == EventStatus.COMPLETED:
                continue
            if event.due_date and event.due_date < today:
                if event.status != EventStatus.OVERDUE:
                    self.db.update_event_status(event.id, self.user_id, EventStatus.OVERDUE)
                    event.status = EventStatus.OVERDUE
                overdue.append(event)

        return overdue

    def mark_complete(self, event_id: int) -> None:
        """Mark an event as completed."""
        self.db.update_event_status(event_id, self.user_id, EventStatus.COMPLETED, date.today())
