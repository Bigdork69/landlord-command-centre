"""Tests for authentication utilities."""

import pytest
from services.auth import hash_password, check_password


def test_hash_password_returns_string():
    """Test that hash_password returns a string."""
    hashed = hash_password("mypassword")
    assert isinstance(hashed, str)
    assert len(hashed) > 0


def test_hash_password_different_each_time():
    """Test that same password produces different hashes (salted)."""
    hash1 = hash_password("mypassword")
    hash2 = hash_password("mypassword")
    assert hash1 != hash2


def test_check_password_correct():
    """Test that correct password validates."""
    hashed = hash_password("mypassword")
    assert check_password("mypassword", hashed) == True


def test_check_password_incorrect():
    """Test that wrong password fails."""
    hashed = hash_password("mypassword")
    assert check_password("wrongpassword", hashed) == False
