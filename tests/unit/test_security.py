import pytest
from data_quality_platform.security.pii_masking import PIIMasker
from data_quality_platform.security.auth import (
    AuthContext, RBACManager, Permission, PermissionDenied, SecretsManager,
)


class TestPIIMasker:
    def test_mask_email_standard(self):
        assert PIIMasker.mask_email("john.smith@example.com") == "j***@example.com"

    def test_mask_email_single_char(self):
        result = PIIMasker.mask_email("a@example.com")
        assert "***@example.com" in result

    def test_mask_email_blank(self):
        assert PIIMasker.mask_email("") == ""

    def test_mask_email_no_at(self):
        assert PIIMasker.mask_email("not-an-email") == "not-an-email"

    def test_mask_phone_standard(self):
        result = PIIMasker.mask_phone("212-555-1234")
        assert "***-***-" in result
        assert "1234" in result

    def test_mask_phone_blank(self):
        assert PIIMasker.mask_phone("") == ""

    def test_mask_address_standard(self):
        result = PIIMasker.mask_address("123 Main Street, New York")
        assert result.startswith("123 Main")
        assert "..." in result

    def test_mask_address_short(self):
        assert PIIMasker.mask_address("short") == "***"

    def test_mask_name_standard(self):
        result = PIIMasker.mask_name("John")
        assert result.startswith("J")
        assert "***" in result

    def test_mask_name_blank(self):
        assert PIIMasker.mask_name("") == ""

    def test_mask_row(self):
        row = {
            "first_name": "John", "last_name": "Smith",
            "email_address": "john.smith@example.com",
            "phone_number": "212-555-1234", "address": "123 Main St",
            "city": "New York", "zip": "10001",
        }
        masked = PIIMasker.mask_row(row)
        assert masked["email_address"] == "j***@example.com"
        assert masked["first_name"] == "J***"
        assert masked["city"] == "New York"  # not PII
        assert masked["zip"] == "10001"  # not PII


class TestRBAC:
    def setup_method(self):
        self.rbac = RBACManager()

    def test_admin_has_all_permissions(self):
        admin = AuthContext(user_id="admin", roles=["admin"])
        for perm in Permission:
            assert self.rbac.check_permission(admin, perm)

    def test_viewer_limited(self):
        viewer = AuthContext(user_id="viewer", roles=["viewer"])
        assert self.rbac.check_permission(viewer, Permission.READ_EVIDENCE)
        assert not self.rbac.check_permission(viewer, Permission.EXPORT_PII)
        assert not self.rbac.check_permission(viewer, Permission.ADMIN)

    def test_operator_has_validate(self):
        op = AuthContext(user_id="op", roles=["operator"])
        assert self.rbac.check_permission(op, Permission.VALIDATE)
        assert not self.rbac.check_permission(op, Permission.EXPORT_PII)

    def test_pii_exporter(self):
        exporter = AuthContext(user_id="exp", roles=["pii_exporter"])
        assert self.rbac.check_permission(exporter, Permission.EXPORT_PII)
        assert not self.rbac.check_permission(exporter, Permission.VALIDATE)

    def test_require_permission_passes(self):
        admin = AuthContext(user_id="admin", roles=["admin"])
        self.rbac.require_permission(admin, Permission.ADMIN)  # no raise

    def test_require_permission_denied(self):
        viewer = AuthContext(user_id="viewer", roles=["viewer"])
        with pytest.raises(PermissionDenied):
            self.rbac.require_permission(viewer, Permission.ADMIN)


class TestSecretsManager:
    def test_get_secret_default(self):
        import os
        key = f"UNIQUE_TEST_KEY_{os.getpid()}"
        result = SecretsManager.get_secret(key, "default_val")
        assert result == "default_val"

    def test_get_config_default(self):
        result = SecretsManager.get_config("NONEXISTENT", "fallback")
        assert result == "fallback"
