"""AI-powered document extraction using Groq API."""

import json
import re
from datetime import date
from decimal import Decimal
from typing import Optional

from config import get_config
from models import ParseResult


EXTRACTION_PROMPT = """You are an expert at extracting information from UK tenancy agreements.
Extract the following fields from this tenancy agreement text. Return ONLY valid JSON, no other text.

Required JSON format:
{{
    "tenant_names": "Full name(s) of tenant(s), comma-separated if multiple",
    "property_address": "Full property address without postcode",
    "postcode": "UK postcode (e.g., SW1A 1AA)",
    "tenancy_start_date": "YYYY-MM-DD format",
    "fixed_term_end_date": "YYYY-MM-DD format or null if periodic/not specified",
    "rent_amount": numeric value only (e.g., 1200.00),
    "rent_frequency": "weekly" or "monthly" or "annually",
    "deposit_amount": numeric value only (e.g., 1200.00) or null if not mentioned
}}

If a field cannot be found, use null. For dates, convert any format to YYYY-MM-DD.
For amounts, extract just the number without currency symbols.

TENANCY AGREEMENT TEXT:
---
{text}
---

Return ONLY the JSON object, nothing else."""


class AIExtractor:
    """Extract structured data from documents using Groq LLM."""

    def __init__(self):
        self.config = get_config()
        self._client = None

    @property
    def is_available(self) -> bool:
        """Check if Groq API is configured."""
        return bool(self.config.groq_api_key)

    @property
    def client(self):
        """Lazy-load Groq client."""
        if self._client is None:
            if not self.is_available:
                raise ValueError("GROQ_API_KEY not configured")
            from groq import Groq
            self._client = Groq(api_key=self.config.groq_api_key)
        return self._client

    def extract_tenancy_data(self, text: str) -> ParseResult:
        """Extract tenancy data from document text using AI."""
        result = ParseResult()
        result.raw_text = text

        if not self.is_available:
            result.warnings.append("Groq API not configured - using regex fallback")
            return result

        try:
            # Truncate text if too long (Groq has token limits)
            max_chars = 15000
            if len(text) > max_chars:
                text = text[:max_chars] + "\n...[truncated]..."

            # Call Groq API
            response = self.client.chat.completions.create(
                model="llama-3.1-8b-instant",  # Fast and free
                messages=[
                    {
                        "role": "user",
                        "content": EXTRACTION_PROMPT.format(text=text)
                    }
                ],
                temperature=0.1,  # Low temperature for consistent extraction
                max_tokens=1000,
            )

            # Parse response
            content = response.choices[0].message.content.strip()

            # Try to extract JSON from response
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if json_match:
                content = json_match.group()

            data = json.loads(content)

            # Map extracted data to result
            result.extracted_fields = {
                'tenant_names': data.get('tenant_names'),
                'property_address': data.get('property_address'),
                'postcode': self._clean_postcode(data.get('postcode')),
                'tenancy_start_date': self._parse_date(data.get('tenancy_start_date')),
                'fixed_term_end_date': self._parse_date(data.get('fixed_term_end_date')),
                'rent_amount': self._parse_amount(data.get('rent_amount')),
                'rent_frequency': data.get('rent_frequency', 'monthly'),
                'deposit_amount': self._parse_amount(data.get('deposit_amount')),
            }

            # Set confidence scores - AI extraction is generally high confidence
            for field, value in result.extracted_fields.items():
                if value is not None:
                    result.confidence_scores[field] = 'HIGH'
                else:
                    result.confidence_scores[field] = 'NOT_FOUND'
                    result.warnings.append(f"{field}: Could not be extracted")

        except json.JSONDecodeError as e:
            result.warnings.append(f"Failed to parse AI response: {e}")
        except Exception as e:
            result.warnings.append(f"AI extraction error: {e}")

        return result

    def _parse_date(self, value) -> Optional[date]:
        """Parse date from various formats."""
        if not value:
            return None
        try:
            if isinstance(value, date):
                return value
            # Handle YYYY-MM-DD format
            return date.fromisoformat(str(value))
        except Exception:
            # Try other formats
            from dateutil import parser as date_parser
            try:
                return date_parser.parse(str(value), dayfirst=True).date()
            except Exception:
                return None

    def _parse_amount(self, value) -> Optional[Decimal]:
        """Parse currency amount."""
        if value is None:
            return None
        try:
            # Handle string with currency symbols
            if isinstance(value, str):
                value = value.replace('£', '').replace(',', '').strip()
            return Decimal(str(value))
        except Exception:
            return None

    def _clean_postcode(self, value) -> Optional[str]:
        """Clean and format UK postcode."""
        if not value:
            return None
        # Remove spaces and uppercase
        postcode = str(value).upper().replace(' ', '')
        # Add space before last 3 characters
        if len(postcode) >= 5:
            postcode = postcode[:-3] + ' ' + postcode[-3:]
        return postcode
