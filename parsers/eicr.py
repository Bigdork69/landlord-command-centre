"""EICR (Electrical Installation Condition Report) PDF parser."""

import re
from datetime import date
from pathlib import Path
from typing import Optional

from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta

from models import CertificateType, ParseResult
from parsers.base import DocumentParser


class EICRParser(DocumentParser):
    """Parser for EICR Certificate PDFs."""

    def parse(self, pdf_path: Path) -> ParseResult:
        """Parse an EICR and extract key fields."""
        result = ParseResult()

        try:
            text = self.extract_text(pdf_path)
            result.raw_text = text
        except Exception as e:
            result.warnings.append(f"Failed to extract text from PDF: {e}")
            return result

        # Try AI extraction first
        try:
            from services.ai_extractor import AIExtractor
            extractor = AIExtractor()

            if extractor.is_available:
                ai_result = extractor.extract_certificate_data(text, "eicr")
                if ai_result.extracted_fields.get('issue_date'):
                    return ai_result
        except Exception:
            pass  # Fall back to regex

        # Regex-based extraction
        return self._extract_with_regex(text, pdf_path)

    def _extract_with_regex(self, text: str, pdf_path: Path) -> ParseResult:
        """Extract EICR data using regex."""
        result = ParseResult()
        result.raw_text = text

        # Patterns for EICR
        patterns = {
            'issue_date': [
                r'date\s+of\s+(?:inspection|report)[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'inspection\s+date[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'report\s+date[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'date[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
            ],
            'next_inspection': [
                r'next\s+inspection\s+(?:due|recommended|by)[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'recommended\s+(?:re-?)?inspection[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r're-?inspection\s+(?:within|by)[:\s]+(\d+)\s+(?:year|month)',
            ],
            'satisfactory': [
                r'overall\s+(?:assessment|condition)[:\s]*(satisfactory|unsatisfactory)',
                r'installation\s+(?:is\s+)?(satisfactory|unsatisfactory)',
                r'(satisfactory|unsatisfactory)\s+(?:for\s+continued\s+use)?',
            ],
            'electrician_name': [
                r'inspector[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
                r'inspected\s+by[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
                r'contractor[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
            ],
        }

        # Extract issue date
        issue_date = self._extract_date(text, patterns['issue_date'])
        result.extracted_fields['issue_date'] = issue_date

        # Extract or calculate expiry date (EICR valid for 5 years for rentals)
        expiry_date = self._extract_date(text, patterns['next_inspection'])
        if not expiry_date and issue_date:
            expiry_date = issue_date + relativedelta(years=5)
        result.extracted_fields['expiry_date'] = expiry_date

        # Check if satisfactory
        satisfactory = self._check_satisfactory(text, patterns['satisfactory'])
        result.extracted_fields['satisfactory'] = satisfactory

        # Extract electrician name
        result.extracted_fields['electrician_name'] = self._extract_text(text, patterns['electrician_name'])

        # Set certificate type
        result.extracted_fields['certificate_type'] = CertificateType.EICR

        # Calculate confidence
        for field, value in result.extracted_fields.items():
            if value is None:
                result.confidence_scores[field] = 'NOT_FOUND'
                if field in ('issue_date', 'expiry_date'):
                    result.warnings.append(f"{field}: Could not be found - manual entry required")
            else:
                result.confidence_scores[field] = 'MEDIUM'

        # Warn if unsatisfactory
        if satisfactory is False:
            result.warnings.append("EICR marked as UNSATISFACTORY - remedial work required!")

        result.warnings.insert(0, "Using regex extraction. Add GROQ_API_KEY for better accuracy.")
        return result

    def _extract_date(self, text: str, patterns: list[str]) -> Optional[date]:
        """Extract a date using the given patterns."""
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                try:
                    # Handle "within X years" format
                    if matches[0].isdigit():
                        return None  # Can't calculate without issue date
                    parsed = date_parser.parse(matches[0], dayfirst=True)
                    return parsed.date()
                except Exception:
                    continue
        return None

    def _extract_text(self, text: str, patterns: list[str]) -> Optional[str]:
        """Extract text using the given patterns."""
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                return matches[0].strip()
        return None

    def _check_satisfactory(self, text: str, patterns: list[str]) -> Optional[bool]:
        """Check if the EICR is satisfactory."""
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                return matches[0].lower() == 'satisfactory'
        return None
