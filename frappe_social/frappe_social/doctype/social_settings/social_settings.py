# Copyright (c) 2026, Frappe Social and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import today, getdate


class SocialSettings(Document):
    def validate(self):
        self.update_twitter_daily_limit()
    
    def update_twitter_daily_limit(self):
        """Update Twitter daily limit based on tier"""
        tier_limits = {
            "Free": 17,
            "Basic": 100,
            "Pro": 1000,
            "Enterprise": 10000
        }
        self.twitter_daily_limit = tier_limits.get(self.twitter_tier, 17)
    
    def can_post_to_twitter(self) -> bool:
        return (self.twitter_posts_today or 0) < self.twitter_daily_limit
    
    def can_post_to_instagram(self) -> bool:
        return (self.instagram_posts_today or 0) < self.instagram_daily_limit
    
    def increment_twitter_posts(self):
        self.twitter_posts_today = (self.twitter_posts_today or 0) + 1
        self.save(ignore_permissions=True)
    
    def increment_instagram_posts(self):
        self.instagram_posts_today = (self.instagram_posts_today or 0) + 1
        self.save(ignore_permissions=True)
    
    def reset_daily_counters(self):
        """Reset daily counters - called by scheduled job"""
        self.twitter_posts_today = 0
        self.instagram_posts_today = 0
        
        # Reset YouTube quota if new day
        if self.youtube_quota_reset_date != today():
            self.youtube_quota_used = 0
            self.youtube_quota_reset_date = today()
        
        self.save(ignore_permissions=True)
