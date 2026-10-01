import os
import pytest
from data_quality_platform.security.pii_masking import PIIMasker
from data_quality_platform.security.auth import RBACManager, AuthContext, Permission, PermissionDenied


class TestSecurityV1:
    """V1 security foundation tests."""

    def test_pii_masking_in_evidence(self, tmp_path):
        """Evidence logs must not contain raw PII."""
        masked = PIIMasker.mask_row({
            "first_name": "John", "last_name": "Smith",
            "email_address": "john.smith@example.com",
            "phone_number": "212-555-1234", "address": "123 Main St",
        })
        assert "john.smith@example.com" not in masked["email_address"]
        assert "John" not in masked["first_name"]
        assert "212-555-1234" not in masked["phone_number"]
        assert "123 Main St" not in masked["address"]

    def test_no_hardcoded_credentials(self):
        """Verify no hardcoded credentials in security module."""
        auth_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data_quality_platform", "security", "auth.py"
        )
        with open(auth_path) as f:
            content = f.read()
        assert "password123" not in content
        assert "secret_key" not in content
        assert "hardcoded" not in content.lower()

    def test_rbac_enforcement(self):
        rbac = RBACManager()
        viewer = AuthContext(user_id="viewer", roles=["viewer"])
        with pytest.raises(PermissionDenied):
            rbac.require_permission(viewer, Permission.ADMIN)

    def test_env_based_config(self):
        """Secrets must come from environment variables."""
        from data_quality_platform.security.auth import SecretsManager
        val = SecretsManager.get_secret("NONEXISTENT_KEY_12345", "default")
        assert val == "default"

    def test_audit_access_logging(self, tmp_path):
        from data_quality_platform.audit.trail import AuditTrail
        at = AuditTrail("sec_test", str(tmp_path))
        at.record_access(user="admin", action="read_evidence", resource="manifest.json")
        assert at.has_event("access_logged")

    def test_pii_masking_various_formats(self):
        """Test masking handles edge cases."""
        assert PIIMasker.mask_email("") == ""
        assert PIIMasker.mask_phone("") == ""
        assert PIIMasker.mask_address("") == ""
        assert PIIMasker.mask_name("") == ""
