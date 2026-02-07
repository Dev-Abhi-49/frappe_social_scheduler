"""
Base Provider for Social Media Platforms
"""

import frappe
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, List


@dataclass
class PublishResult:
    success: bool
    post_id: Optional[str] = None
    post_url: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: Optional[Dict] = None


@dataclass
class AnalyticsResult:
    success: bool
    metrics: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    raw_response: Optional[Dict] = None


@dataclass
class TokenRefreshResult:
    success: bool
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_in: Optional[int] = None
    error_message: Optional[str] = None


class BaseProvider(ABC):
    """Abstract base class for social media providers"""
    
    PLATFORM: str = ""
    MAX_CONTENT_LENGTH: int = 0
    SUPPORTS_IMAGES: bool = False
    SUPPORTS_VIDEO: bool = False
    MAX_IMAGES: int = 0

    def __init__(self, integration_name: str = None):
        self.settings = frappe.get_single("Social Settings")
        self.integration = None
        self.integration_name = integration_name
        if integration_name:
            self.integration = frappe.get_doc("Social Integration", integration_name)

    def get_integration_doc(self, integration_name: str = None):
        """Get integration document"""
        name = integration_name or self.integration_name
        if not name:
            frappe.throw("Integration name required")
        return frappe.get_doc("Social Integration", name)

    @abstractmethod
    def publish_post(self, content: str = None, media_files: List = None, **kwargs) -> PublishResult:
        """Publish a post to the platform"""
        pass

    @abstractmethod
    def fetch_account_analytics(self, integration_name: str = None) -> AnalyticsResult:
        """Fetch account-level analytics"""
        pass

    @abstractmethod
    def fetch_post_analytics(self, post_id: str, integration_name: str = None) -> AnalyticsResult:
        """Fetch analytics for a specific post"""
        pass

    @abstractmethod
    def get_daily_limit(self) -> int:
        """Get daily rate limit for this platform"""
        pass

    def refresh_token(self, integration_name: str = None) -> TokenRefreshResult:
        """Refresh OAuth token - override in subclass if supported"""
        return TokenRefreshResult(success=False, error_message="Token refresh not supported")

    def increment_rate_limit(self):
        """Increment daily rate limit counter"""
        cache_key = f"social_rate_limit_{self.PLATFORM.lower()}"
        current = frappe.cache.get_value(cache_key) or 0
        frappe.cache.set_value(cache_key, current + 1, expires_in_sec=86400)

    def check_rate_limit(self) -> bool:
        """Check if under daily rate limit"""
        cache_key = f"social_rate_limit_{self.PLATFORM.lower()}"
        current = frappe.cache.get_value(cache_key) or 0
        return current < self.get_daily_limit()
