"""Compliance timeline generator - stub for initial testing."""

from database import Database
from models import Tenancy


class TimelineGenerator:
    """Generate compliance timeline events for tenancies."""

    def __init__(self, db: Database):
        self.db = db

    def generate_for_tenancy(self, tenancy: Tenancy) -> list:
        """Generate compliance events for a tenancy. Returns list of created events."""
        # Stub - will be implemented in Step 7
        return []
