"""
Base Provider for Ad Platforms
Defines the abstract interface all ad platform providers must implement
"""

import frappe
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)


@dataclass
class PublishResult:
    success: bool
    adlabel_ids: Optional[List[str]] = None
    campaign_id: Optional[str] = None
    url: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: Optional[Dict] = None
    adset_id: Optional[str] = None
    ad_id: Optional[str] = None
    creative_id: Optional[str] = None
    image_url: Optional[str] = None
    image_hash: Optional[str] = None


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
    
@dataclass
class AudienceResult:
    success: bool
    audience_id: Optional[str] = None
    error_message: Optional[str] = None
    raw_response: Optional[Dict] = None

class BaseProvider(ABC):
    """
    Abstract base class for ad platform providers
    All providers must implement these methods to handle their specific platform APIs
    """

    PLATFORM: str = ""
    MAX_BUDGET: int = 0
    MAX_IMAGES: int = 0
    MAX_CONTENT_LENGTH: int = 0
    SUPPORTS_IMAGES = False
    SUPPORTS_VIDEO = False

    def __init__(self, integration_name: str = None):
        """
        Initialize provider with integration settings

        Args:
            integration_name: Name of Ads Account Integration document
        """
        self.settings = frappe.get_single("Social Settings")
        self.integration = None
        self.integration_name = integration_name
        if integration_name:
            try:
                self.integration = frappe.get_doc("Ads Account Integration", integration_name)
            except frappe.DoesNotExistError:
                logger.error(f"Integration not found: {integration_name}")
                frappe.throw(f"Integration not found: {integration_name}")

    def get_integration_doc(self, integration_name: str = None):
        """
        Get integration document

        Args:
            integration_name: Name of integration (uses stored name if not provided)

        Returns:
            Ads Account Integration document
        """
        name = integration_name or self.integration_name
        if not name:
            frappe.throw("Integration name required")
        try:
            return frappe.get_doc("Ads Account Integration", name)
        except frappe.DoesNotExistError:
            logger.error(f"Integration document not found: {name}")
            frappe.throw(f"Integration not found: {name}")

    @abstractmethod
    def create_campaign(self, payload: Dict) -> PublishResult:
        """Publish/launch a post or campaign to the platform"""
        pass

    @abstractmethod
    def fetch_account_analytics(self) -> AnalyticsResult:
        """Fetch account-level analytics"""
        pass

    @abstractmethod
    def fetch_post_analytics(self, campaign_id: str) -> AnalyticsResult:
        """Fetch analytics for a specific campaign/post"""
        pass

    @abstractmethod
    def get_daily_limit(self) -> int:
        """Get daily rate limit for this platform"""
        pass

    def refresh_token(self, integration_name: str = None) -> TokenRefreshResult:
        """
        Refresh OAuth token

        Args:
            integration_name: Name of integration to refresh token for

        Returns:
            TokenRefreshResult with new tokens if successful
        """
        return TokenRefreshResult(success=False, error_message="Token refresh not supported")

    def increment_rate_limit(self):
        """Increment API call counter for rate limiting"""
        cache_key = f"ad_rate_limit_{self.PLATFORM.lower()}"
        current = frappe.cache.get_value(cache_key) or 0
        frappe.cache.set_value(cache_key, current + 1, expires_in_sec=86400)

    def check_rate_limit(self) -> bool:
        """
        Check if under rate limit

        Returns:
            True if API calls are under the daily limit, False otherwise
        """
        cache_key = f"ad_rate_limit_{self.PLATFORM.lower()}"
        current = frappe.cache.get_value(cache_key) or 0
        return current < self.get_daily_limit()
