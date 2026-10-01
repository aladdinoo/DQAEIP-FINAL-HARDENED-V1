"""PII masking utilities.

V1 Security Foundation:
- Email masking
- Phone masking
- Address masking
- Name masking

Evidence logs MUST NOT print raw PII.
Flag Preview preserves source columns per V1 contract,
but security docs state this output is sensitive.
"""

import re
from typing import Dict, Any


class PIIMasker:
    """Masks PII fields for safe logging and evidence output."""

    @staticmethod
    def mask_email(email: str) -> str:
        """Mask email: john.smith@example.com -> j***@example.com"""
        if not email or "@" not in email:
            return email
        local, domain = email.rsplit("@", 1)
        if len(local) <= 1:
            return f"***@{domain}"
        return f"{local[0]}***@{domain}"

    @staticmethod
    def mask_phone(phone: str) -> str:
        """Mask phone: 212-555-1234 -> ***-***-1234"""
        if not phone:
            return phone
        digits = re.sub(r"\D", "", phone)
        if len(digits) < 4:
            return "***"
        masked_digits = "*" * (len(digits) - 4) + digits[-4:]
        # Try to preserve formatting
        if "-" in phone:
            parts = phone.split("-")
            if len(parts) == 3:
                return f"***-***-{parts[2]}"
        return masked_digits

    @staticmethod
    def mask_address(address: str) -> str:
        """Mask address: show only first 8 chars + ..."""
        if not address:
            return address
        if len(address) <= 8:
            return "***"
        return address[:8] + "..."

    @staticmethod
    def mask_name(name: str) -> str:
        """Mask name: John -> J***, Smith-Jones -> S*********"""
        if not name:
            return name
        # Get first alpha character
        for i, ch in enumerate(name):
            if ch.isalpha():
                return name[:i] + ch + "***"
        return "***"

    @classmethod
    def mask_row(cls, row: Dict[str, Any]) -> Dict[str, Any]:
        """Mask all PII fields in a row for safe logging."""
        masked = {}
        pii_fields = {
            "email_address": cls.mask_email,
            "phone_number": cls.mask_phone,
            "address": cls.mask_address,
            "first_name": cls.mask_name,
            "last_name": cls.mask_name,
        }
        for key, value in row.items():
            if key in pii_fields:
                masked[key] = pii_fields[key](str(value))
            else:
                masked[key] = value
        return masked
