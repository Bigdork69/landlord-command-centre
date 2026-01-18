"""Tenancy agreement PDF parser with AI-powered extraction."""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

from dateutil import parser as date_parser

from models import ParseResult
from parsers.base import DocumentParser


class TenancyParser(DocumentParser):
    """Parser for tenancy agreement PDFs. Uses AI when available, falls back to regex."""

    def parse(self, pdf_path: Path) -> ParseResult:
        """Parse a tenancy agreement PDF and extract key fields."""
        # Extract text from PDF
        try:
            text = self.extract_text(pdf_path)
        except Exception as e:
            result = ParseResult()
            result.warnings.append(f"Failed to extract text from PDF: {e}")
            return result

        # Try AI extraction first (much more accurate)
        try:
            from services.ai_extractor import AIExtractor
            extractor = AIExtractor()

            if extractor.is_available:
                result = extractor.extract_tenancy_data(text)
                if result.extracted_fields.get('tenant_names') or result.extracted_fields.get('rent_amount'):
                    # AI extraction succeeded, return results
                    return result
                # AI didn't extract much, fall through to regex
        except Exception as e:
            pass  # Fall back to regex

        # Fallback: regex-based extraction
        return self._extract_with_regex(text)

    def _extract_with_regex(self, text: str) -> ParseResult:
        """Extract tenancy data using regex patterns (fallback method)."""
        result = ParseResult()
        result.raw_text = text

        # Regex patterns for extracting tenancy information
        patterns = {
            'tenancy_start': [
                r'tenancy\s+(?:shall\s+)?(?:commence[sd]?|begin[s]?|start[s]?)\s+(?:on\s+)?(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'(?:start|commencement)\s+date[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'from\s+(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4})',
                r'term\s+(?:shall\s+)?(?:commence|begin|start)\s+(?:on\s+)?(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'(?:commencing|starting|beginning)\s+(?:on\s+)?(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
            ],
            'tenancy_end': [
                r'(?:until|to|ending|end\s+date)[:\s]+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'fixed\s+term.*?(?:ending|until|to)\s+(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
                r'expir(?:y|es|ing)\s+(?:on\s+)?(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})',
            ],
            'rent_amount': [
                r'rent\s+(?:of\s+)?£([\d,]+(?:\.\d{2})?)\s+(?:per\s+)?(?:calendar\s+)?month',
                r'monthly\s+rent[:\s]+£([\d,]+(?:\.\d{2})?)',
                r'£([\d,]+(?:\.\d{2})?)\s+(?:pcm|per\s+(?:calendar\s+)?month)',
                r'rent[:\s]+£([\d,]+(?:\.\d{2})?)',
                r'£([\d,]+(?:\.\d{2})?)\s+per\s+month',
            ],
            'deposit_amount': [
                r'deposit\s+(?:of\s+)?£([\d,]+(?:\.\d{2})?)',
                r'security\s+deposit[:\s]+£([\d,]+(?:\.\d{2})?)',
                r'£([\d,]+(?:\.\d{2})?)\s+(?:as\s+)?(?:a\s+)?(?:security\s+)?deposit',
            ],
            'property_address': [
                r'property\s+(?:known\s+as|at|address)[:\s]+([^\n]+)',
                r'premises[:\s]+([^\n]+)',
                r'(?:the\s+)?property\s+(?:is\s+)?(?:located\s+)?at[:\s]+([^\n]+)',
            ],
            'tenant_name': [
                r'tenant[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
                r'between.*?and\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\s+\(?.*tenant',
                r'name\s+of\s+tenant[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)',
            ],
        }

        # Extract each field
        result.extracted_fields['tenancy_start_date'] = self._extract_date(text, patterns['tenancy_start'])
        result.extracted_fields['fixed_term_end_date'] = self._extract_date(text, patterns['tenancy_end'])
        result.extracted_fields['rent_amount'] = self._extract_amount(text, patterns['rent_amount'])
        result.extracted_fields['rent_frequency'] = 'monthly'
        result.extracted_fields['deposit_amount'] = self._extract_amount(text, patterns['deposit_amount'])
        result.extracted_fields['property_address'] = self._extract_text(text, patterns['property_address'])
        result.extracted_fields['tenant_names'] = self._extract_text(text, patterns['tenant_name'])
        result.extracted_fields['postcode'] = self._extract_postcode(text)

        # Calculate confidence scores
        for field, value in result.extracted_fields.items():
            if value is None:
                result.confidence_scores[field] = 'NOT_FOUND'
                result.warnings.append(f"{field}: Could not be found - manual entry required")
            else:
                result.confidence_scores[field] = 'MEDIUM'

        result.warnings.insert(0, "Using regex extraction (less accurate). Add GROQ_API_KEY for better results.")

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
                extracted = re.sub(r'\s+', ' ', extracted)
                extracted = extracted.strip('.,;:')
                if len(extracted) > 3:
                    return extracted
        return None

    def _extract_postcode(self, text: str) -> Optional[str]:
        """Extract UK postcode from text."""
        pattern = r'([A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2})'
        matches = re.findall(pattern, text.upper())
        if matches:
            postcode = matches[0].replace(' ', '')
            if len(postcode) >= 5:
                postcode = postcode[:-3] + ' ' + postcode[-3:]
            return postcode
        return None
