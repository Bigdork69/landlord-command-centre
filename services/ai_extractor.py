"""AI-powered document extraction using Groq API."""

import json
import re
from datetime import date
from decimal import Decimal
from typing import Optional

from config import get_config
from models import CertificateType, ParseResult


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

    def extract_certificate_data(self, text: str, cert_type: str) -> ParseResult:
        """Extract certificate data from document text using AI."""
        result = ParseResult()
        result.raw_text = text

        if not self.is_available:
            result.warnings.append("Groq API not configured - using regex fallback")
            return result

        # Certificate-specific prompts
        prompts = {
            'gas_safety': """You are an expert at extracting information from UK Gas Safety Certificates (CP12).
Extract the following fields. Return ONLY valid JSON, no other text.

Required JSON format:
{{
    "issue_date": "YYYY-MM-DD format (date of inspection)",
    "expiry_date": "YYYY-MM-DD format (next inspection due, usually 12 months after issue)",
    "gas_safe_number": "Gas Safe registration number (5-7 digits)",
    "engineer_name": "Name of the gas engineer",
    "property_address": "Address where inspection was done"
}}

If a field cannot be found, use null. For dates, convert any format to YYYY-MM-DD.

CERTIFICATE TEXT:
---
{text}
---

Return ONLY the JSON object, nothing else.""",

            'eicr': """You are an expert at extracting information from UK Electrical Installation Condition Reports (EICR).
Extract the following fields. Return ONLY valid JSON, no other text.

Required JSON format:
{{
    "issue_date": "YYYY-MM-DD format (date of inspection)",
    "expiry_date": "YYYY-MM-DD format (next inspection due, usually 5 years for rentals)",
    "satisfactory": true or false (whether installation is satisfactory for continued use),
    "electrician_name": "Name of the inspector/electrician",
    "property_address": "Address where inspection was done"
}}

If a field cannot be found, use null. For dates, convert any format to YYYY-MM-DD.

CERTIFICATE TEXT:
---
{text}
---

Return ONLY the JSON object, nothing else.""",

            'epc': """You are an expert at extracting information from UK Energy Performance Certificates (EPC).
Extract the following fields. Return ONLY valid JSON, no other text.

Required JSON format:
{{
    "issue_date": "YYYY-MM-DD format (date of assessment)",
    "expiry_date": "YYYY-MM-DD format (valid until date, usually 10 years after issue)",
    "rating": "Energy rating letter A-G",
    "score": numeric score 1-100,
    "certificate_number": "Certificate reference number (format: XXXX-XXXX-XXXX-XXXX-XXXX)",
    "property_address": "Address of the property"
}}

If a field cannot be found, use null. For dates, convert any format to YYYY-MM-DD.

CERTIFICATE TEXT:
---
{text}
---

Return ONLY the JSON object, nothing else."""
        }

        if cert_type not in prompts:
            result.warnings.append(f"Unknown certificate type: {cert_type}")
            return result

        try:
            # Truncate text if too long
            max_chars = 15000
            if len(text) > max_chars:
                text = text[:max_chars] + "\n...[truncated]..."

            # Call Groq API
            response = self.client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {
                        "role": "user",
                        "content": prompts[cert_type].format(text=text)
                    }
                ],
                temperature=0.1,
                max_tokens=1000,
            )

            # Parse response
            content = response.choices[0].message.content.strip()

            # Try to extract JSON from response
            json_match = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if json_match:
                content = json_match.group()

            data = json.loads(content)

            # Map certificate type
            cert_type_map = {
                'gas_safety': CertificateType.GAS_SAFETY,
                'eicr': CertificateType.EICR,
                'epc': CertificateType.EPC,
            }

            # Map extracted data to result
            result.extracted_fields = {
                'issue_date': self._parse_date(data.get('issue_date')),
                'expiry_date': self._parse_date(data.get('expiry_date')),
                'certificate_type': cert_type_map.get(cert_type),
            }

            # Add type-specific fields
            if cert_type == 'gas_safety':
                result.extracted_fields['gas_safe_number'] = data.get('gas_safe_number')
                result.extracted_fields['engineer_name'] = data.get('engineer_name')
            elif cert_type == 'eicr':
                result.extracted_fields['satisfactory'] = data.get('satisfactory')
                result.extracted_fields['electrician_name'] = data.get('electrician_name')
            elif cert_type == 'epc':
                result.extracted_fields['rating'] = data.get('rating', '').upper() if data.get('rating') else None
                result.extracted_fields['score'] = data.get('score')
                result.extracted_fields['certificate_number'] = data.get('certificate_number')

            # Set confidence scores
            for field, value in result.extracted_fields.items():
                if value is not None:
                    result.confidence_scores[field] = 'HIGH'
                else:
                    result.confidence_scores[field] = 'NOT_FOUND'
                    if field in ('issue_date', 'expiry_date'):
                        result.warnings.append(f"{field}: Could not be extracted")

            # Type-specific warnings
            if cert_type == 'eicr' and result.extracted_fields.get('satisfactory') is False:
                result.warnings.append("EICR marked as UNSATISFACTORY - remedial work required!")
            if cert_type == 'epc':
                rating = result.extracted_fields.get('rating')
                if rating and rating in ('F', 'G'):
                    result.warnings.append(f"EPC rating {rating} is below minimum E required for lettings!")

        except json.JSONDecodeError as e:
            result.warnings.append(f"Failed to parse AI response: {e}")
        except Exception as e:
            result.warnings.append(f"AI extraction error: {e}")

        return result
