"""Tests for data models."""

import pytest
from models import User


def test_user_creation():
    """Test basic User creation."""
    user = User(
        id=1,
        email="test@example.com",
        password_hash="hashed",
        name="Test User"
    )
    assert user.email == "test@example.com"
    assert user.name == "Test User"
    assert user.is_active == True


def test_user_flask_login_interface():
    """Test User implements Flask-Login interface."""
    user = User(id=1, email="test@example.com", password_hash="x", name="Test")

    # Flask-Login requires these
    assert user.is_authenticated == True
    assert user.is_active == True
    assert user.is_anonymous == False
    assert user.get_id() == "1"
