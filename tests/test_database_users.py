"""Tests for user database operations."""

import pytest
from pathlib import Path
import tempfile

from database import Database
from models import User


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
