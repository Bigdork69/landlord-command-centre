"""Tests for user database operations."""

import pytest
from pathlib import Path
import tempfile

from database import Database
from models import Property, PropertyType, User


@pytest.fixture
def db():
    """Create a test database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        database = Database(db_path)
        database.initialize()
        yield database


def test_create_user(db):
    """Test creating a user."""
    user = User(email="test@example.com", password_hash="hashed123", name="Test User")
    user_id = db.create_user(user)
    assert user_id == 1


def test_get_user_by_email(db):
    """Test finding user by email."""
    user = User(email="test@example.com", password_hash="hashed123", name="Test User")
    db.create_user(user)

    found = db.get_user_by_email("test@example.com")
    assert found is not None
    assert found.email == "test@example.com"
    assert found.name == "Test User"


def test_get_user_by_email_not_found(db):
    """Test finding non-existent user returns None."""
    found = db.get_user_by_email("nobody@example.com")
    assert found is None


def test_get_user_by_id(db):
    """Test finding user by ID."""
    user = User(email="test@example.com", password_hash="hashed123", name="Test User")
    user_id = db.create_user(user)

    found = db.get_user(user_id)
    assert found is not None
    assert found.id == user_id


def test_create_property_with_user_id(db):
    """Test creating property associated with a user."""
    # Create a user first
    user = User(email="test@example.com", password_hash="hashed", name="Test")
    user_id = db.create_user(user)

    # Create property for that user
    prop = Property(address="123 Test St", postcode="AB1 2CD", property_type=PropertyType.HOUSE)
    prop_id = db.create_property(prop, user_id=user_id)

    # Verify property belongs to user
    props = db.list_properties(user_id=user_id)
    assert len(props) == 1
    assert props[0].address == "123 Test St"


def test_list_properties_filters_by_user(db):
    """Test that list_properties only returns user's properties."""
    # Create two users
    user1_id = db.create_user(User(email="user1@example.com", password_hash="h", name="User 1"))
    user2_id = db.create_user(User(email="user2@example.com", password_hash="h", name="User 2"))

    # Create property for each
    db.create_property(Property(address="User 1 Property", postcode="A1 1AA"), user_id=user1_id)
    db.create_property(Property(address="User 2 Property", postcode="B2 2BB"), user_id=user2_id)

    # Each user should only see their own
    user1_props = db.list_properties(user_id=user1_id)
    user2_props = db.list_properties(user_id=user2_id)

    assert len(user1_props) == 1
    assert user1_props[0].address == "User 1 Property"
    assert len(user2_props) == 1
    assert user2_props[0].address == "User 2 Property"
