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


class RequiredDocument(str, Enum):
    """Documents legally required to serve to tenants."""
    HOW_TO_RENT = "how_to_rent"
    GAS_SAFETY_CERT = "gas_safety_cert"
    EICR = "eicr"
    EPC = "epc"
    DEPOSIT_PROTECTION = "deposit_protection"
    PRESCRIBED_INFO = "prescribed_info"
    RIGHT_TO_RENT = "right_to_rent"

    @property
    def display_name(self) -> str:
        names = {
            "how_to_rent": "How to Rent Guide",
            "gas_safety_cert": "Gas Safety Certificate",
            "eicr": "EICR",
            "epc": "EPC",
            "deposit_protection": "Deposit Protection Certificate",
            "prescribed_info": "Deposit Prescribed Information",
            "right_to_rent": "Right to Rent Check",
        }
        return names.get(self.value, self.value)

    @property
    def legal_requirement(self) -> str:
        requirements = {
            "how_to_rent": "Deregulation Act 2015 - Required for valid Section 21",
            "gas_safety_cert": "Gas Safety Regs 1998 - Before move-in & within 28 days of renewal",
            "eicr": "Electrical Safety Regs 2020 - Before move-in & within 28 days",
            "epc": "Energy Performance Regs - Before tenancy starts",
            "deposit_protection": "Housing Act 2004 - Within 30 days of receiving deposit",
            "prescribed_info": "Housing Act 2004 - Within 30 days of protecting deposit",
            "right_to_rent": "Immigration Act 2014 - Before tenancy starts",
        }
        return requirements.get(self.value, "")

    @property
    def resources(self) -> dict:
        """Return download/reference URLs for this document type."""
        resources = {
            "how_to_rent": {
                "gov_uk": "https://www.gov.uk/government/publications/how-to-rent",
                "label": "Download from gov.uk",
            },
            "right_to_rent": {
                "gov_uk": "https://www.gov.uk/government/publications/landlords-guide-to-right-to-rent-checks",
                "documents": "https://www.gov.uk/government/publications/right-to-rent-document-checks-a-user-guide",
                "label": "Landlord Guide",
            },
            "prescribed_info": {
                "dps": "https://content-assets.computershare.com/eh96rkuu9740/768AMjuCtiqgYqOJXmIGie/f1b8ce74a8ad48ee4a01487cdb8318fe/DPS-Prescribed-Information-Form.pdf",
                "mydeposits": "https://www.mydeposits.co.uk/wp-content/uploads/2021/04/mydeposits-custodial-PI-template.pdf",
                "label": "Template Downloads",
            },
            "epc": {
                "lookup": "https://find-energy-certificate.digital.communities.gov.uk/find-a-certificate/search-by-postcode?postcode=",
                "label": "Look up EPC",
            },
        }
        return resources.get(self.value, {})


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
class ServedDocument:
    """Record of a document served to tenant."""
    id: Optional[int] = None
    tenancy_id: int = 0
    document_type: RequiredDocument = RequiredDocument.HOW_TO_RENT
    served_date: Optional[date] = None
    proof_path: str = ""
    notes: str = ""
    created_at: datetime = field(default_factory=datetime.now)


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
