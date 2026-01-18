"""EPC (Energy Performance Certificate) PDF parser."""

import re
from datetime import date
from pathlib import Path
from typing import Optional

from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta

from models import CertificateType, ParseResult
from parsers.base import DocumentParser


class EPCParser(DocumentParser):
    """Parser for EPC Certificate PDFs."""

    def parse(self, pdf_path: Path) -> ParseResult:
        """Parse an EPC and extract key fields."""
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
                ai_result = extractor.extract_certificate_data(text, "epc")
                if ai_result.extracted_fields.get('issue_date'):
                    return ai_result
        except Exception:
            pass  # Fall back to regex

        # Regex-based extraction
        return self._extract_with_regex(text, pdf_path)

    def _extract_with_regex(self, text: str, pdf_path: Path) -> ParseResult:
        """Extract EPC data using regex."""
        result = ParseResult()
        result.raw_text = text

        # Patterns for EPC
        patterns = {
            'issue_date': [
                r'date\s+of\s+(?:assessment|certificate)[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'certificate\s+date[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'issued[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'date[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
            ],
            'expiry_date': [
                r'valid\s+until[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'expiry[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'expires[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
            ],
            'rating': [
                r'current\s+energy\s+(?:efficiency\s+)?rating[:\s]*([A-G])',
                r'energy\s+rating[:\s]*([A-G])',
                r'epc\s+rating[:\s]*([A-G])',
                r'\brating[:\s]*([A-G])\b',
                r'\b([A-G])\s*\(\d+',  # A (92) style
            ],
            'score': [
                r'current\s+(?:energy\s+)?score[:\s]*(\d+)',
                r'energy\s+(?:efficiency\s+)?score[:\s]*(\d+)',
                r'\b([A-G])\s*\((\d+)\)',  # Extract score from A (92)
            ],
            'certificate_number': [
                r'certificate\s+(?:reference\s+)?(?:number|no)[:\s]+(\d{4}-\d{4}-\d{4}-\d{4}-\d{4})',
                r'rr?n[:\s]+(\d{4}-\d{4}-\d{4}-\d{4}-\d{4})',
            ],
        }

        # Extract issue date
        issue_date = self._extract_date(text, patterns['issue_date'])
        result.extracted_fields['issue_date'] = issue_date

        # Extract or calculate expiry date (EPC valid for 10 years)
        expiry_date = self._extract_date(text, patterns['expiry_date'])
        if not expiry_date and issue_date:
            expiry_date = issue_date + relativedelta(years=10)
        result.extracted_fields['expiry_date'] = expiry_date

        # Extract rating (A-G)
        rating = self._extract_rating(text, patterns['rating'])
        result.extracted_fields['rating'] = rating

        # Extract score
        score = self._extract_score(text, patterns['score'])
        result.extracted_fields['score'] = score

        # Extract certificate number
        result.extracted_fields['certificate_number'] = self._extract_text(text, patterns['certificate_number'])

        # Set certificate type
        result.extracted_fields['certificate_type'] = CertificateType.EPC

        # Calculate confidence
        for field, value in result.extracted_fields.items():
            if value is None:
                result.confidence_scores[field] = 'NOT_FOUND'
                if field in ('issue_date', 'expiry_date', 'rating'):
                    result.warnings.append(f"{field}: Could not be found - manual entry required")
            else:
                result.confidence_scores[field] = 'MEDIUM'

        # Warn if rating below E (minimum for rentals)
        if rating and rating in ('F', 'G'):
            result.warnings.append(f"EPC rating {rating} is below minimum E required for lettings!")

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

    def _extract_rating(self, text: str, patterns: list[str]) -> Optional[str]:
        """Extract EPC rating (A-G)."""
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                rating = matches[0].upper()
                if rating in 'ABCDEFG':
                    return rating
        return None

    def _extract_score(self, text: str, patterns: list[str]) -> Optional[int]:
        """Extract EPC score (1-100)."""
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                try:
                    # Handle tuple from grouped patterns
                    if isinstance(matches[0], tuple):
                        score = int(matches[0][-1])  # Take last group (the number)
                    else:
                        score = int(matches[0])
                    if 1 <= score <= 100:
                        return score
                except (ValueError, IndexError):
                    continue
        return None
