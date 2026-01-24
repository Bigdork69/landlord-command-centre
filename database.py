"""SQLite database setup and connection management."""

import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Generator, Optional

from models import (
    Certificate,
    CertificateType,
    ComplianceEvent,
    EventPriority,
    EventStatus,
    Property,
    PropertyType,
    RentFrequency,
    RequiredDocument,
    ServedDocument,
    Tenancy,
    User,
)


# Database schema version for migrations
SCHEMA_VERSION = 1

SCHEMA = """
-- Properties table
CREATE TABLE IF NOT EXISTS properties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address TEXT NOT NULL,
    postcode TEXT NOT NULL,
    property_type TEXT NOT NULL DEFAULT 'house',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tenancies table
CREATE TABLE IF NOT EXISTS tenancies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER NOT NULL,
    tenant_names TEXT NOT NULL,
    tenancy_start_date DATE,
    fixed_term_end_date DATE,
    rent_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
    rent_frequency TEXT NOT NULL DEFAULT 'monthly',
    deposit_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
    deposit_protected BOOLEAN DEFAULT 0,
    deposit_protection_date DATE,
    deposit_scheme TEXT,
    prescribed_info_served BOOLEAN DEFAULT 0,
    prescribed_info_date DATE,
    how_to_rent_served BOOLEAN DEFAULT 0,
    how_to_rent_date DATE,
    is_active BOOLEAN DEFAULT 1,
    document_path TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (property_id) REFERENCES properties(id)
);

-- Certificates table
CREATE TABLE IF NOT EXISTS certificates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER NOT NULL,
    certificate_type TEXT NOT NULL,
    issue_date DATE,
    expiry_date DATE,
    document_path TEXT,
    served_to_tenant_date DATE,
    reference_number TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (property_id) REFERENCES properties(id)
);

-- Compliance events table
CREATE TABLE IF NOT EXISTS compliance_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property_id INTEGER NOT NULL,
    tenancy_id INTEGER,
    event_type TEXT NOT NULL,
    event_name TEXT NOT NULL,
    due_date DATE,
    completed_date DATE,
    status TEXT NOT NULL DEFAULT 'pending',
    priority TEXT NOT NULL DEFAULT 'medium',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (property_id) REFERENCES properties(id),
    FOREIGN KEY (tenancy_id) REFERENCES tenancies(id)
);

-- Documents served to tenants
CREATE TABLE IF NOT EXISTS served_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenancy_id INTEGER NOT NULL,
    document_type TEXT NOT NULL,
    served_date DATE,
    proof_path TEXT,
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (tenancy_id) REFERENCES tenancies(id),
    UNIQUE(tenancy_id, document_type)
);

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);
"""


class Database:
    """SQLite database manager with connection pooling."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_directory()

    def _ensure_directory(self) -> None:
        """Ensure the database directory exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections."""
        conn = sqlite3.connect(
            self.db_path,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        """Initialize the database schema."""
        with self.connection() as conn:
            conn.executescript(SCHEMA)
            # Set schema version if not exists
            cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
            if cursor.fetchone() is None:
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (SCHEMA_VERSION,),
                )

    def get_schema_version(self) -> int:
        """Get current schema version."""
        with self.connection() as conn:
            cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
            row = cursor.fetchone()
            return row["version"] if row else 0

    # Property CRUD operations

    def create_property(self, prop: Property) -> int:
        """Create a new property and return its ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO properties (address, postcode, property_type)
                VALUES (?, ?, ?)
                """,
                (prop.address, prop.postcode, prop.property_type.value),
            )
            return cursor.lastrowid

    def get_property(self, property_id: int) -> Optional[Property]:
        """Get a property by ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM properties WHERE id = ?", (property_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_property(row)
            return None

    def get_property_by_address(self, address: str, postcode: str) -> Optional[Property]:
        """Find a property by address and postcode."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM properties WHERE address = ? AND postcode = ?",
                (address, postcode),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_property(row)
            return None

    def list_properties(self) -> list[Property]:
        """List all properties."""
        with self.connection() as conn:
            cursor = conn.execute("SELECT * FROM properties ORDER BY created_at DESC")
            return [self._row_to_property(row) for row in cursor.fetchall()]

    def _row_to_property(self, row: sqlite3.Row) -> Property:
        """Convert database row to Property object."""
        return Property(
            id=row["id"],
            address=row["address"],
            postcode=row["postcode"],
            property_type=PropertyType(row["property_type"]),
            created_at=self._parse_datetime(row["created_at"]),
        )

    def _parse_datetime(self, value) -> datetime:
        """Parse datetime from database (handles both string and datetime)."""
        if value is None:
            return datetime.now()
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)

    def _parse_date(self, value) -> Optional[date]:
        """Parse date from database (handles both string and date)."""
        if value is None:
            return None
        if isinstance(value, date):
            return value
        return date.fromisoformat(value)

    # Tenancy CRUD operations

    def create_tenancy(self, tenancy: Tenancy) -> int:
        """Create a new tenancy and return its ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tenancies (
                    property_id, tenant_names, tenancy_start_date, fixed_term_end_date,
                    rent_amount, rent_frequency, deposit_amount, deposit_protected,
                    deposit_protection_date, deposit_scheme, prescribed_info_served,
                    prescribed_info_date, how_to_rent_served, how_to_rent_date,
                    is_active, document_path, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenancy.property_id,
                    tenancy.tenant_names,
                    tenancy.tenancy_start_date.isoformat()
                    if tenancy.tenancy_start_date
                    else None,
                    tenancy.fixed_term_end_date.isoformat()
                    if tenancy.fixed_term_end_date
                    else None,
                    str(tenancy.rent_amount),
                    tenancy.rent_frequency.value,
                    str(tenancy.deposit_amount),
                    tenancy.deposit_protected,
                    tenancy.deposit_protection_date.isoformat()
                    if tenancy.deposit_protection_date
                    else None,
                    tenancy.deposit_scheme,
                    tenancy.prescribed_info_served,
                    tenancy.prescribed_info_date.isoformat()
                    if tenancy.prescribed_info_date
                    else None,
                    tenancy.how_to_rent_served,
                    tenancy.how_to_rent_date.isoformat()
                    if tenancy.how_to_rent_date
                    else None,
                    tenancy.is_active,
                    tenancy.document_path,
                    tenancy.notes,
                ),
            )
            return cursor.lastrowid

    def get_tenancy(self, tenancy_id: int) -> Optional[Tenancy]:
        """Get a tenancy by ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM tenancies WHERE id = ?", (tenancy_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_tenancy(row)
            return None

    def list_tenancies(self, active_only: bool = False) -> list[Tenancy]:
        """List tenancies, optionally filtered to active only."""
        with self.connection() as conn:
            if active_only:
                cursor = conn.execute(
                    "SELECT * FROM tenancies WHERE is_active = 1 ORDER BY created_at DESC"
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM tenancies ORDER BY created_at DESC"
                )
            return [self._row_to_tenancy(row) for row in cursor.fetchall()]

    def list_tenancies_for_property(
        self, property_id: int, active_only: bool = False
    ) -> list[Tenancy]:
        """List tenancies for a specific property."""
        with self.connection() as conn:
            if active_only:
                cursor = conn.execute(
                    """SELECT * FROM tenancies
                       WHERE property_id = ? AND is_active = 1
                       ORDER BY created_at DESC""",
                    (property_id,),
                )
            else:
                cursor = conn.execute(
                    "SELECT * FROM tenancies WHERE property_id = ? ORDER BY created_at DESC",
                    (property_id,),
                )
            return [self._row_to_tenancy(row) for row in cursor.fetchall()]

    def update_tenancy(self, tenancy: Tenancy) -> None:
        """Update an existing tenancy."""
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE tenancies SET
                    tenant_names = ?, tenancy_start_date = ?, fixed_term_end_date = ?,
                    rent_amount = ?, rent_frequency = ?, deposit_amount = ?,
                    deposit_protected = ?, deposit_protection_date = ?, deposit_scheme = ?,
                    prescribed_info_served = ?, prescribed_info_date = ?,
                    how_to_rent_served = ?, how_to_rent_date = ?,
                    is_active = ?, document_path = ?, notes = ?
                WHERE id = ?
                """,
                (
                    tenancy.tenant_names,
                    tenancy.tenancy_start_date.isoformat()
                    if tenancy.tenancy_start_date
                    else None,
                    tenancy.fixed_term_end_date.isoformat()
                    if tenancy.fixed_term_end_date
                    else None,
                    str(tenancy.rent_amount),
                    tenancy.rent_frequency.value,
                    str(tenancy.deposit_amount),
                    tenancy.deposit_protected,
                    tenancy.deposit_protection_date.isoformat()
                    if tenancy.deposit_protection_date
                    else None,
                    tenancy.deposit_scheme,
                    tenancy.prescribed_info_served,
                    tenancy.prescribed_info_date.isoformat()
                    if tenancy.prescribed_info_date
                    else None,
                    tenancy.how_to_rent_served,
                    tenancy.how_to_rent_date.isoformat()
                    if tenancy.how_to_rent_date
                    else None,
                    tenancy.is_active,
                    tenancy.document_path,
                    tenancy.notes,
                    tenancy.id,
                ),
            )

    def _row_to_tenancy(self, row: sqlite3.Row) -> Tenancy:
        """Convert database row to Tenancy object."""
        return Tenancy(
            id=row["id"],
            property_id=row["property_id"],
            tenant_names=row["tenant_names"],
            tenancy_start_date=self._parse_date(row["tenancy_start_date"]),
            fixed_term_end_date=self._parse_date(row["fixed_term_end_date"]),
            rent_amount=Decimal(row["rent_amount"]) if row["rent_amount"] else Decimal("0"),
            rent_frequency=RentFrequency(row["rent_frequency"]),
            deposit_amount=Decimal(row["deposit_amount"])
            if row["deposit_amount"]
            else Decimal("0"),
            deposit_protected=bool(row["deposit_protected"]),
            deposit_protection_date=self._parse_date(row["deposit_protection_date"]),
            deposit_scheme=row["deposit_scheme"] or "",
            prescribed_info_served=bool(row["prescribed_info_served"]),
            prescribed_info_date=self._parse_date(row["prescribed_info_date"]),
            how_to_rent_served=bool(row["how_to_rent_served"]),
            how_to_rent_date=self._parse_date(row["how_to_rent_date"]),
            is_active=bool(row["is_active"]),
            document_path=row["document_path"] or "",
            notes=row["notes"] or "",
            created_at=self._parse_datetime(row["created_at"]),
        )

    # Certificate CRUD operations

    def create_certificate(self, cert: Certificate) -> int:
        """Create a new certificate and return its ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO certificates (
                    property_id, certificate_type, issue_date, expiry_date,
                    document_path, served_to_tenant_date, reference_number, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cert.property_id,
                    cert.certificate_type.value,
                    cert.issue_date.isoformat() if cert.issue_date else None,
                    cert.expiry_date.isoformat() if cert.expiry_date else None,
                    cert.document_path,
                    cert.served_to_tenant_date.isoformat()
                    if cert.served_to_tenant_date
                    else None,
                    cert.reference_number,
                    cert.notes,
                ),
            )
            return cursor.lastrowid

    def get_certificate(self, cert_id: int) -> Optional[Certificate]:
        """Get a certificate by ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM certificates WHERE id = ?", (cert_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_certificate(row)
            return None

    def list_certificates_for_property(self, property_id: int) -> list[Certificate]:
        """List all certificates for a property."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM certificates WHERE property_id = ? ORDER BY created_at DESC",
                (property_id,),
            )
            return [self._row_to_certificate(row) for row in cursor.fetchall()]

    def get_latest_certificate(
        self, property_id: int, cert_type: CertificateType
    ) -> Optional[Certificate]:
        """Get the most recent certificate of a type for a property."""
        with self.connection() as conn:
            cursor = conn.execute(
                """SELECT * FROM certificates
                   WHERE property_id = ? AND certificate_type = ?
                   ORDER BY issue_date DESC LIMIT 1""",
                (property_id, cert_type.value),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_certificate(row)
            return None

    def _row_to_certificate(self, row: sqlite3.Row) -> Certificate:
        """Convert database row to Certificate object."""
        return Certificate(
            id=row["id"],
            property_id=row["property_id"],
            certificate_type=CertificateType(row["certificate_type"]),
            issue_date=self._parse_date(row["issue_date"]),
            expiry_date=self._parse_date(row["expiry_date"]),
            document_path=row["document_path"] or "",
            served_to_tenant_date=self._parse_date(row["served_to_tenant_date"]),
            reference_number=row["reference_number"] or "",
            notes=row["notes"] or "",
            created_at=self._parse_datetime(row["created_at"]),
        )

    def update_certificate(self, cert_id: int, issue_date=None, expiry_date=None, notes: str = None) -> bool:
        """Update certificate dates and/or notes."""
        with self.connection() as conn:
            updates = []
            params = []

            if issue_date is not None:
                updates.append("issue_date = ?")
                params.append(issue_date.isoformat() if issue_date else None)

            if expiry_date is not None:
                updates.append("expiry_date = ?")
                params.append(expiry_date.isoformat() if expiry_date else None)

            if notes is not None:
                updates.append("notes = ?")
                params.append(notes)

            if not updates:
                return False

            params.append(cert_id)
            conn.execute(
                f"UPDATE certificates SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            return True

    # Compliance Events CRUD operations

    def create_event(self, event: ComplianceEvent) -> int:
        """Create a new compliance event and return its ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO compliance_events (
                    property_id, tenancy_id, event_type, event_name,
                    due_date, completed_date, status, priority, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.property_id,
                    event.tenancy_id,
                    event.event_type,
                    event.event_name,
                    event.due_date.isoformat() if event.due_date else None,
                    event.completed_date.isoformat() if event.completed_date else None,
                    event.status.value,
                    event.priority.value,
                    event.notes,
                ),
            )
            return cursor.lastrowid

    def get_event(self, event_id: int) -> Optional[ComplianceEvent]:
        """Get an event by ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM compliance_events WHERE id = ?", (event_id,)
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_event(row)
            return None

    def list_events(
        self,
        property_id: Optional[int] = None,
        tenancy_id: Optional[int] = None,
        status: Optional[EventStatus] = None,
    ) -> list[ComplianceEvent]:
        """List compliance events with optional filters."""
        with self.connection() as conn:
            query = "SELECT * FROM compliance_events WHERE 1=1"
            params = []

            if property_id is not None:
                query += " AND property_id = ?"
                params.append(property_id)
            if tenancy_id is not None:
                query += " AND tenancy_id = ?"
                params.append(tenancy_id)
            if status is not None:
                query += " AND status = ?"
                params.append(status.value)

            query += " ORDER BY due_date ASC"
            cursor = conn.execute(query, params)
            return [self._row_to_event(row) for row in cursor.fetchall()]

    def update_event_status(
        self, event_id: int, status: EventStatus, completed_date: Optional[date] = None
    ) -> None:
        """Update the status of a compliance event."""
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE compliance_events
                SET status = ?, completed_date = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    completed_date.isoformat() if completed_date else None,
                    event_id,
                ),
            )

    def delete_events_for_tenancy(self, tenancy_id: int) -> None:
        """Delete all compliance events for a tenancy."""
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM compliance_events WHERE tenancy_id = ?",
                (tenancy_id,),
            )

    def delete_events_for_property(self, property_id: int) -> None:
        """Delete all compliance events for a property."""
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM compliance_events WHERE property_id = ?",
                (property_id,),
            )

    def delete_tenancy(self, tenancy_id: int) -> None:
        """Delete a tenancy and its associated events."""
        with self.connection() as conn:
            # Delete associated events first
            conn.execute(
                "DELETE FROM compliance_events WHERE tenancy_id = ?",
                (tenancy_id,),
            )
            # Delete the tenancy
            conn.execute(
                "DELETE FROM tenancies WHERE id = ?",
                (tenancy_id,),
            )

    def delete_certificates_for_property(self, property_id: int) -> None:
        """Delete all certificates for a property."""
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM certificates WHERE property_id = ?",
                (property_id,),
            )

    def delete_property(self, property_id: int) -> None:
        """Delete a property and all associated data."""
        with self.connection() as conn:
            # Delete associated events
            conn.execute(
                "DELETE FROM compliance_events WHERE property_id = ?",
                (property_id,),
            )
            # Delete associated tenancies
            conn.execute(
                "DELETE FROM tenancies WHERE property_id = ?",
                (property_id,),
            )
            # Delete associated certificates
            conn.execute(
                "DELETE FROM certificates WHERE property_id = ?",
                (property_id,),
            )
            # Delete the property
            conn.execute(
                "DELETE FROM properties WHERE id = ?",
                (property_id,),
            )

    def _row_to_event(self, row: sqlite3.Row) -> ComplianceEvent:
        """Convert database row to ComplianceEvent object."""
        return ComplianceEvent(
            id=row["id"],
            property_id=row["property_id"],
            tenancy_id=row["tenancy_id"],
            event_type=row["event_type"],
            event_name=row["event_name"],
            due_date=self._parse_date(row["due_date"]),
            completed_date=self._parse_date(row["completed_date"]),
            status=EventStatus(row["status"]),
            priority=EventPriority(row["priority"]),
            notes=row["notes"] or "",
            created_at=self._parse_datetime(row["created_at"]),
        )

    # Served Documents CRUD operations

    def mark_document_served(
        self, tenancy_id: int, document_type: RequiredDocument, served_date: date, proof_path: str = "", notes: str = ""
    ) -> int:
        """Mark a document as served to tenant. Returns the record ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO served_documents (tenancy_id, document_type, served_date, proof_path, notes)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(tenancy_id, document_type) DO UPDATE SET
                    served_date = excluded.served_date,
                    proof_path = excluded.proof_path,
                    notes = excluded.notes
                """,
                (tenancy_id, document_type.value, served_date.isoformat(), proof_path, notes),
            )
            return cursor.lastrowid

    def get_served_documents(self, tenancy_id: int) -> list[ServedDocument]:
        """Get all served documents for a tenancy."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM served_documents WHERE tenancy_id = ? ORDER BY served_date",
                (tenancy_id,),
            )
            return [self._row_to_served_document(row) for row in cursor.fetchall()]

    def get_served_document(self, tenancy_id: int, document_type: RequiredDocument) -> Optional[ServedDocument]:
        """Get a specific served document record."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM served_documents WHERE tenancy_id = ? AND document_type = ?",
                (tenancy_id, document_type.value),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_served_document(row)
            return None

    def delete_served_document(self, tenancy_id: int, document_type: RequiredDocument) -> None:
        """Delete a served document record."""
        with self.connection() as conn:
            conn.execute(
                "DELETE FROM served_documents WHERE tenancy_id = ? AND document_type = ?",
                (tenancy_id, document_type.value),
            )

    def _row_to_served_document(self, row: sqlite3.Row) -> ServedDocument:
        """Convert database row to ServedDocument object."""
        return ServedDocument(
            id=row["id"],
            tenancy_id=row["tenancy_id"],
            document_type=RequiredDocument(row["document_type"]),
            served_date=self._parse_date(row["served_date"]),
            proof_path=row["proof_path"] or "",
            notes=row["notes"] or "",
            created_at=self._parse_datetime(row["created_at"]),
        )

    # User operations
    def create_user(self, user: User) -> int:
        """Create a new user and return their ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                """INSERT INTO users (email, password_hash, name, is_active)
                   VALUES (?, ?, ?, ?)""",
                (user.email, user.password_hash, user.name, user.is_active),
            )
            return cursor.lastrowid

    def get_user(self, user_id: int) -> Optional[User]:
        """Get a user by ID."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            )
            row = cursor.fetchone()
            if row:
                return User(
                    id=row["id"],
                    email=row["email"],
                    password_hash=row["password_hash"],
                    name=row["name"],
                    is_active=bool(row["is_active"]),
                    created_at=row["created_at"],
                )
            return None

    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get a user by email address."""
        with self.connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            )
            row = cursor.fetchone()
            if row:
                return User(
                    id=row["id"],
                    email=row["email"],
                    password_hash=row["password_hash"],
                    name=row["name"],
                    is_active=bool(row["is_active"]),
                    created_at=row["created_at"],
                )
            return None
