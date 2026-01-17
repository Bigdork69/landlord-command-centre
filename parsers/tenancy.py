"""Tenancy agreement PDF parser."""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

from dateutil import parser as date_parser

from models import ParseResult
from parsers.base import DocumentParser


class TenancyParser(DocumentParser):
    """Parser for tenancy agreement PDFs."""

    # Regex patterns for extracting tenancy information
    PATTERNS = {
        'tenancy_start': [
            r'tenancy\s+(?:shall\s+)?(?:commence[sd]?|begin[s]?|start[s]?)\s+(?:on\s+)?(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
            r'(?:start|commencement)\s+date[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
            r'from\s+(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})',
            r'term\s+(?:shall\s+)?(?:commence|begin|start)\s+(?:on\s+)?(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
            r'(?:commencing|starting|beginning)\s+(?:on\s+)?(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
        ],
        'tenancy_end': [
            r'(?:until|to|ending|end\s+date)[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
            r'fixed\s+term\s+(?:of\s+)?\d+\s+(?:month|year)s?\s+(?:ending|until)\s+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
            r'expir(?:y|es|ing)\s+(?:on\s+)?(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
        ],
        'rent_amount': [
            r'rent\s+of\s+£([\d,]+(?:\.\d{2})?)\s+per\s+(?:calendar\s+)?month',
            r'monthly\s+rent[:\s]+£([\d,]+(?:\.\d{2})?)',
            r'£([\d,]+(?:\.\d{2})?)\s+(?:pcm|per\s+(?:calendar\s+)?month)',
            r'rent[:\s]+£([\d,]+(?:\.\d{2})?)\s+(?:per\s+)?(?:month|pcm)',
            r'(?:sum|amount)\s+of\s+£([\d,]+(?:\.\d{2})?)\s+(?:per\s+)?(?:month|monthly)',
        ],
        'rent_weekly': [
            r'rent\s+of\s+£([\d,]+(?:\.\d{2})?)\s+per\s+week',
            r'weekly\s+rent[:\s]+£([\d,]+(?:\.\d{2})?)',
            r'£([\d,]+(?:\.\d{2})?)\s+(?:pw|per\s+week)',
        ],
        'deposit_amount': [
            r'deposit\s+of\s+£([\d,]+(?:\.\d{2})?)',
            r'security\s+deposit[:\s]+£([\d,]+(?:\.\d{2})?)',
            r'deposit[:\s]+£([\d,]+(?:\.\d{2})?)',
            r'£([\d,]+(?:\.\d{2})?)\s+(?:as\s+)?(?:a\s+)?(?:security\s+)?deposit',
        ],
        'property_address': [
            r'property\s+(?:known\s+as|at|address)[:\s]+([^\n]+)',
            r'premises[:\s]+([^\n]+)',
            r'(?:the\s+)?(?:rental\s+)?property\s+(?:is\s+)?(?:located\s+)?at[:\s]+([^\n]+)',
            r'address\s+of\s+(?:the\s+)?(?:rental\s+)?property[:\s]+([^\n]+)',
        ],
        'tenant_name': [
            r'tenant[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
            r'between.*?and\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+\(?.*tenant',
            r'(?:the\s+)?tenant[:\s]+(?:Mr|Mrs|Ms|Miss|Dr)?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
            r'name\s+of\s+tenant[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
        ],
        'postcode': [
            r'([A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2})',
        ],
    }

    def parse(self, pdf_path: Path) -> ParseResult:
        """Parse a tenancy agreement PDF and extract key fields."""
        result = ParseResult()

        try:
            text = self.extract_text(pdf_path)
            result.raw_text = text
        except Exception as e:
            result.warnings.append(f"Failed to extract text: {e}")
            return result

        # Extract each field
        result.extracted_fields['tenancy_start_date'] = self._extract_date(
            text, self.PATTERNS['tenancy_start']
        )
        result.confidence_scores['tenancy_start_date'] = self._get_confidence(
            text, self.PATTERNS['tenancy_start'], result.extracted_fields['tenancy_start_date']
        )

        result.extracted_fields['fixed_term_end_date'] = self._extract_date(
            text, self.PATTERNS['tenancy_end']
        )
        result.confidence_scores['fixed_term_end_date'] = self._get_confidence(
            text, self.PATTERNS['tenancy_end'], result.extracted_fields['fixed_term_end_date']
        )

        # Try monthly rent first, then weekly
        result.extracted_fields['rent_amount'] = self._extract_amount(
            text, self.PATTERNS['rent_amount']
        )
        result.extracted_fields['rent_frequency'] = 'monthly'

        if result.extracted_fields['rent_amount'] is None:
            result.extracted_fields['rent_amount'] = self._extract_amount(
                text, self.PATTERNS['rent_weekly']
            )
            if result.extracted_fields['rent_amount']:
                result.extracted_fields['rent_frequency'] = 'weekly'

        result.confidence_scores['rent_amount'] = self._get_confidence(
            text, self.PATTERNS['rent_amount'] + self.PATTERNS['rent_weekly'],
            result.extracted_fields['rent_amount']
        )

        result.extracted_fields['deposit_amount'] = self._extract_amount(
            text, self.PATTERNS['deposit_amount']
        )
        result.confidence_scores['deposit_amount'] = self._get_confidence(
            text, self.PATTERNS['deposit_amount'], result.extracted_fields['deposit_amount']
        )

        result.extracted_fields['property_address'] = self._extract_text(
            text, self.PATTERNS['property_address']
        )
        result.confidence_scores['property_address'] = self._get_confidence(
            text, self.PATTERNS['property_address'], result.extracted_fields['property_address']
        )

        result.extracted_fields['tenant_names'] = self._extract_text(
            text, self.PATTERNS['tenant_name']
        )
        result.confidence_scores['tenant_names'] = self._get_confidence(
            text, self.PATTERNS['tenant_name'], result.extracted_fields['tenant_names']
        )

        result.extracted_fields['postcode'] = self._extract_postcode(text)
        result.confidence_scores['postcode'] = 'HIGH' if result.extracted_fields['postcode'] else 'NOT_FOUND'

        # Add warnings for low confidence or missing fields
        for field, confidence in result.confidence_scores.items():
            if confidence == 'NOT_FOUND':
                result.warnings.append(f"{field}: Could not be found - manual entry required")
            elif confidence == 'LOW':
                result.warnings.append(f"{field}: Multiple matches found - please verify")
            elif confidence == 'MEDIUM':
                result.warnings.append(f"{field}: Single match found - review recommended")

        return result

    def _extract_date(self, text: str, patterns: list[str]) -> Optional[date]:
        """Extract a date using the given patterns."""
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                date_str = matches[0]
                try:
                    parsed = date_parser.parse(date_str, dayfirst=True)
                    return parsed.date()
                except Exception:
                    continue
        return None

    def _extract_amount(self, text: str, patterns: list[str]) -> Optional[Decimal]:
        """Extract a currency amount using the given patterns."""
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                amount_str = matches[0].replace(',', '')
                try:
                    return Decimal(amount_str)
                except Exception:
                    continue
        return None

    def _extract_text(self, text: str, patterns: list[str]) -> Optional[str]:
        """Extract text using the given patterns."""
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                extracted = matches[0].strip()
                # Clean up common artifacts
                extracted = re.sub(r'\s+', ' ', extracted)
                extracted = extracted.strip('.,;:')
                if len(extracted) > 3:  # Avoid tiny matches
                    return extracted
        return None

    def _extract_postcode(self, text: str) -> Optional[str]:
        """Extract UK postcode from text."""
        pattern = r'([A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2})'
        matches = re.findall(pattern, text.upper())
        if matches:
            # Return the most common postcode (likely the property address)
            return matches[0].replace(' ', '').upper()
        return None

    def _get_confidence(self, text: str, patterns: list[str], value) -> str:
        """Calculate confidence score for an extracted value."""
        if value is None:
            return 'NOT_FOUND'

        total_matches = 0
        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            total_matches += len(matches)

        if total_matches == 1:
            return 'HIGH'
        elif total_matches == 2:
            return 'MEDIUM'
        else:
            return 'LOW'
