"""
Installation hooks for Frappe Social
"""

import frappe


def after_install():
    """Run after app installation"""
    create_default_settings()
    create_custom_fields()
    print("Frappe Social installed successfully!")


def create_default_settings():
    """Create default Social Settings if not exists"""
    if not frappe.db.exists("Social Settings"):
        settings = frappe.new_doc("Social Settings")
        settings.insert(ignore_permissions=True)
        frappe.db.commit()


def create_custom_fields():
    """Create any custom fields needed"""
    # Add custom fields to other DocTypes if needed
    pass


def before_tests():
    """Setup for running tests"""
    # Create test fixtures
    pass
