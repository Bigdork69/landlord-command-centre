"""Gas Safety Certificate PDF parser."""

import re
from datetime import date
from pathlib import Path
from typing import Optional

from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta

from models import Certificate, CertificateType, ParseResult
from parsers.base import DocumentParser


class GasSafetyParser(DocumentParser):
    """Parser for Gas Safety Certificate PDFs."""

    def parse(self, pdf_path: Path) -> ParseResult:
        """Parse a Gas Safety Certificate and extract key fields."""
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
                ai_result = extractor.extract_certificate_data(text, "gas_safety")
                if ai_result.extracted_fields.get('issue_date'):
                    return ai_result
        except Exception:
            pass  # Fall back to regex

        # Regex-based extraction
        return self._extract_with_regex(text, pdf_path)

    def _extract_with_regex(self, text: str, pdf_path: Path) -> ParseResult:
        """Extract Gas Safety Certificate data using regex."""
        result = ParseResult()
        result.raw_text = text

        # Patterns for Gas Safety Certificate
        patterns = {
            'issue_date': [
                r'date\s+of\s+(?:inspection|check)[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'inspection\s+date[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'date[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'completed\s+(?:on\s+)?(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
            ],
            'expiry_date': [
                r'next\s+(?:inspection|check)\s+(?:due|by)[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'expiry[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'valid\s+until[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
            ],
            'gas_safe_number': [
                r'gas\s+safe\s+(?:register\s+)?(?:number|no|#)[:\s]+(\d{5,7})',
                r'registration\s+(?:number|no)[:\s]+(\d{5,7})',
            ],
            'engineer_name': [
                r'engineer[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
                r'inspected\s+by[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
            ],
        }

        # Extract issue date
        issue_date = self._extract_date(text, patterns['issue_date'])
        result.extracted_fields['issue_date'] = issue_date

        # Extract or calculate expiry date (Gas Safety valid for 12 months)
        expiry_date = self._extract_date(text, patterns['expiry_date'])
        if not expiry_date and issue_date:
            expiry_date = issue_date + relativedelta(years=1)
        result.extracted_fields['expiry_date'] = expiry_date

        # Extract Gas Safe number
        result.extracted_fields['gas_safe_number'] = self._extract_text(text, patterns['gas_safe_number'])

        # Extract engineer name
        result.extracted_fields['engineer_name'] = self._extract_text(text, patterns['engineer_name'])

        # Set certificate type
        result.extracted_fields['certificate_type'] = CertificateType.GAS_SAFETY

        # Calculate confidence
        for field, value in result.extracted_fields.items():
            if value is None:
                result.confidence_scores[field] = 'NOT_FOUND'
                if field in ('issue_date', 'expiry_date'):
                    result.warnings.append(f"{field}: Could not be found - manual entry required")
            else:
                result.confidence_scores[field] = 'MEDIUM'

        result.warnings.insert(0, "Using regex extraction. Add GROQ_API_KEY for better accuracy.")
        return result

    def _extract_date(self, text: str, patterns: list[str]) -> Optional[date]:
        """Extract a date using the given patterns."""
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                try:
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
