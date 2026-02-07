# Copyright (c) 2026, Frappe Social and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SocialAnalytics(Document):
    def calculate_engagement_rate(self):
        total_engagement = (self.likes or 0) + (self.comments or 0) + (self.shares or 0) + (self.saves or 0)
        if self.reach and self.reach > 0:
            self.engagement_rate = round((total_engagement / self.reach) * 100, 2)
        elif self.impressions and self.impressions > 0:
            self.engagement_rate = round((total_engagement / self.impressions) * 100, 2)
        else:
            self.engagement_rate = 0
    
    def add_metric(self, metric_name: str, metric_value, previous_analytics=None):
        previous_value = None
        if previous_analytics:
            for m in previous_analytics.metrics:
                if m.metric_name == metric_name:
                    previous_value = m.metric_value
                    break
        
        change = None
        change_percent = None
        if previous_value is not None and metric_value is not None:
            change = metric_value - previous_value
            if previous_value > 0:
                change_percent = round((change / previous_value) * 100, 2)
        
        self.append("metrics", {
            "metric_name": metric_name,
            "metric_value": metric_value,
            "previous_value": previous_value,
            "change": change,
            "change_percent": change_percent
        })
