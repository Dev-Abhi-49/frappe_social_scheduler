# ad_creative.py

import frappe
from frappe import _
from frappe.model.document import Document
import json


class AdCreative(Document):
    """Child table - Ad Creative row inside Ad Post"""

    def validate(self):
        if not self.creative_name:
            frappe.throw(_("Creative Name is required"))
        
        # Validate at least one content field is filled
        if not self.body and not self.title and not self.link_url:
            frappe.throw(_("At least one of Body, Title or Link URL is required"))
        
        # Validate URL format if provided
        if self.link_url:
            self._validate_url(self.link_url)
        
        if self.object_url:
            self._validate_url(self.object_url)
    
    def _validate_url(self, url):
        """Validate URL format"""
        if not url.startswith(('http://', 'https://')):
            frappe.throw(_("URL must start with http:// or https://"))

