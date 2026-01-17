"""Data models for landlord-command-centre."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class PropertyType(str, Enum):
    """Type of rental property."""
    HOUSE = "house"
    FLAT = "flat"
    MAISONETTE = "maisonette"
    STUDIO = "studio"
    ROOM = "room"
    OTHER = "other"


class RentFrequency(str, Enum):
    """Frequency of rent payments."""
    WEEKLY = "weekly"
    FORTNIGHTLY = "fortnightly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUALLY = "annually"


class CertificateType(str, Enum):
    """Type of compliance certificate."""
    GAS_SAFETY = "gas_safety"
    EICR = "eicr"
    EPC = "epc"
    FIRE_SAFETY = "fire_safety"


class EventStatus(str, Enum):
    """Status of a compliance event."""
    PENDING = "pending"
    COMPLETED = "completed"
    OVERDUE = "overdue"


class EventPriority(str, Enum):
    """Priority level of a compliance event."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Property:
    """A rental property."""
    id: Optional[int] = None
    address: str = ""
    postcode: str = ""
    property_type: PropertyType = PropertyType.HOUSE
    created_at: datetime = field(default_factory=datetime.now)

    def __str__(self) -> str:
        return f"{self.address}, {self.postcode}"


@dataclass
class Tenancy:
    """A tenancy agreement for a property."""
    id: Optional[int] = None
    property_id: int = 0
    tenant_names: str = ""
    tenancy_start_date: Optional[date] = None
    fixed_term_end_date: Optional[date] = None
    rent_amount: Decimal = Decimal("0.00")
    rent_frequency: RentFrequency = RentFrequency.MONTHLY
    deposit_amount: Decimal = Decimal("0.00")
    deposit_protected: bool = False
    deposit_protection_date: Optional[date] = None
    deposit_scheme: str = ""
    prescribed_info_served: bool = False
    prescribed_info_date: Optional[date] = None
    how_to_rent_served: bool = False
    how_to_rent_date: Optional[date] = None
    is_active: bool = True
    document_path: str = ""
    notes: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def is_periodic(self) -> bool:
        """Check if tenancy is in periodic phase."""
        if self.fixed_term_end_date is None:
            return True
        return date.today() > self.fixed_term_end_date

    @property
    def weekly_rent(self) -> Decimal:
        """Calculate weekly rent equivalent."""
        if self.rent_frequency == RentFrequency.WEEKLY:
            return self.rent_amount
        elif self.rent_frequency == RentFrequency.FORTNIGHTLY:
            return self.rent_amount / 2
        elif self.rent_frequency == RentFrequency.MONTHLY:
            return (self.rent_amount * 12) / 52
        elif self.rent_frequency == RentFrequency.QUARTERLY:
            return (self.rent_amount * 4) / 52
        elif self.rent_frequency == RentFrequency.ANNUALLY:
            return self.rent_amount / 52
        return self.rent_amount


@dataclass
class Certificate:
    """A compliance certificate for a property."""
    id: Optional[int] = None
    property_id: int = 0
    certificate_type: CertificateType = CertificateType.GAS_SAFETY
    issue_date: Optional[date] = None
    expiry_date: Optional[date] = None
    document_path: str = ""
    served_to_tenant_date: Optional[date] = None
    reference_number: str = ""
    notes: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def is_expired(self) -> bool:
        """Check if certificate is expired."""
        if self.expiry_date is None:
            return False
        return date.today() > self.expiry_date

    @property
    def days_until_expiry(self) -> Optional[int]:
        """Days until certificate expires (negative if expired)."""
        if self.expiry_date is None:
            return None
        return (self.expiry_date - date.today()).days


@dataclass
class ComplianceEvent:
    """A compliance deadline or event."""
    id: Optional[int] = None
    property_id: int = 0
    tenancy_id: Optional[int] = None
    event_type: str = ""
    event_name: str = ""
    due_date: Optional[date] = None
    completed_date: Optional[date] = None
    status: EventStatus = EventStatus.PENDING
    priority: EventPriority = EventPriority.MEDIUM
    notes: str = ""
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def is_overdue(self) -> bool:
        """Check if event is overdue."""
        if self.status == EventStatus.COMPLETED:
            return False
        if self.due_date is None:
            return False
        return date.today() > self.due_date

    @property
    def days_until_due(self) -> Optional[int]:
        """Days until event is due (negative if overdue)."""
        if self.due_date is None:
            return None
        return (self.due_date - date.today()).days


@dataclass
class ParseResult:
    """Result from parsing a document."""
    extracted_fields: dict = field(default_factory=dict)
    confidence_scores: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    raw_text: str = ""

    def get_field(self, name: str, default=None):
        """Get an extracted field value."""
        return self.extracted_fields.get(name, default)

    def get_confidence(self, name: str) -> str:
        """Get confidence level for a field (HIGH, MEDIUM, LOW, NOT_FOUND)."""
        return self.confidence_scores.get(name, "NOT_FOUND")


@dataclass
class ValidationResult:
    """Result from validating a tenancy."""
    is_valid: bool = True
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    info: list = field(default_factory=list)

    def add_error(self, message: str, code: str = "") -> None:
        """Add an error (compliance failure)."""
        self.errors.append({"message": message, "code": code})
        self.is_valid = False

    def add_warning(self, message: str, code: str = "") -> None:
        """Add a warning (potential issue)."""
        self.warnings.append({"message": message, "code": code})

    def add_info(self, message: str, code: str = "") -> None:
        """Add informational message."""
        self.info.append({"message": message, "code": code})
