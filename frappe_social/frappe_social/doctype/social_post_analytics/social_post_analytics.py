# Copyright (c) 2026, Frappe Social and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SocialPostAnalytics(Document):
    def before_save(self):
        """Calculate engagement rate before saving"""
        self.calculate_engagement_rate()

    def calculate_engagement_rate(self):
        """Calculate engagement rate from metrics"""
        total_engagement = (self.likes or 0) + (self.comments or 0) + (self.shares or 0) + (self.saves or 0)
        if self.reach and self.reach > 0:
            self.engagement_rate = round((total_engagement / self.reach) * 100, 2)
        elif self.impressions and self.impressions > 0:
            self.engagement_rate = round((total_engagement / self.impressions) * 100, 2)
        else:
            self.engagement_rate = 0

    def add_metric(self, metric_name: str, metric_value, previous_analytics=None):
        """Add metric tracking for post-level analytics"""
        pass
