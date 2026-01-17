"""Base parser infrastructure for document extraction."""

import re
from abc import ABC, abstractmethod
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF
from dateutil import parser as date_parser

from models import ParseResult


class DocumentParser(ABC):
    """Abstract base class for document parsers."""

    def extract_text(self, pdf_path: Path) -> str:
        """Extract all text from a PDF file."""
        text = ""
        try:
            doc = fitz.open(pdf_path)
            for page in doc:
                text += page.get_text()
            doc.close()
        except Exception as e:
            raise ValueError(f"Failed to read PDF: {e}")
        return text

    def find_dates(self, text: str) -> list[tuple[str, date]]:
        """Find all dates in text. Returns list of (original_string, parsed_date)."""
        dates = []

        # Common UK date patterns
        patterns = [
            # 15/01/2025, 15-01-2025, 15.01.2025
            r'\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})\b',
            # 15th January 2025, 15 January 2025
            r'\b(\d{1,2}(?:st|nd|rd|th)?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})\b',
            # January 15, 2025
            r'\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4})\b',
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                date_str = match.group(1)
                try:
                    parsed = date_parser.parse(date_str, dayfirst=True)
                    dates.append((date_str, parsed.date()))
                except Exception:
                    continue

        return dates

    def find_currency(self, text: str) -> list[tuple[str, Decimal]]:
        """Find all currency amounts in text. Returns list of (original_string, amount)."""
        amounts = []

        # UK currency patterns
        patterns = [
            # £1,200.00, £1200, £1,200
            r'£([\d,]+(?:\.\d{2})?)',
            # 1,200.00 GBP, 1200 GBP
            r'([\d,]+(?:\.\d{2})?)\s*(?:GBP|gbp)',
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text):
                amount_str = match.group(1).replace(',', '')
                try:
                    amount = Decimal(amount_str)
                    amounts.append((match.group(0), amount))
                except Exception:
                    continue

        return amounts

    def calculate_confidence(self, matches: int, context_matches: int = 0) -> str:
        """Calculate confidence level based on number of matches."""
        if matches == 0:
            return "NOT_FOUND"
        elif matches == 1 and context_matches > 0:
            return "HIGH"
        elif matches == 1:
            return "MEDIUM"
        elif matches > 1:
            return "LOW"  # Multiple matches, unclear which is correct
        return "MEDIUM"

    @abstractmethod
    def parse(self, pdf_path: Path) -> ParseResult:
        """Parse a document and extract relevant fields."""
        pass
