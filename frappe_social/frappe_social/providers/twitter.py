"""
Twitter/X Provider - API v2 + v1.1 for media

Requirements:
- Dual OAuth: OAuth 2.0 + PKCE for v2, OAuth 1.0a for v1.1 media upload
- Tiers: Free (17/day), Basic ($200/mo, 100/day), Pro ($5K/mo)
- offline.access scope required for refresh tokens
- Media: Images 5MB/4 per tweet, Videos 512MB/140s
"""

import frappe
import requests
from frappe_social.frappe_social.providers.base import BaseProvider, PublishResult, AnalyticsResult, TokenRefreshResult


class TwitterProvider(BaseProvider):
    PLATFORM = "Twitter"
    MAX_CONTENT_LENGTH = 280
    SUPPORTS_IMAGES = True
    SUPPORTS_VIDEO = True
    MAX_IMAGES = 4

    TIER_LIMITS = {"Free": 17, "Basic": 100, "Pro": 1000, "Enterprise": 10000}

    def __init__(self, integration_name: str = None):
        super().__init__(integration_name)
        self.client_id = self.settings.twitter_client_id
        self.client_secret = self.settings.get_password("twitter_client_secret")

    def publish_post(self, content: str = None, media_files: list = None, **kwargs) -> PublishResult:
        if not self.integration:
            return PublishResult(success=False, error_message="No integration configured")
        
        access_token = self.integration.get_password("access_token")
        if not access_token:
            return PublishResult(success=False, error_message="No access token")
        
        # Check rate limit
        if not self._check_rate_limit():
            return PublishResult(success=False, error_message="Daily tweet limit reached")
        
        tweet_data = {"text": content or ""}
        
        # TODO: Media upload requires OAuth 1.0a - not implemented yet
        # if media_files:
        #     media_ids = self._upload_media(media_files)
        #     if media_ids:
        #         tweet_data["media"] = {"media_ids": media_ids}
        
        try:
            response = requests.post("https://api.twitter.com/2/tweets",
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                json=tweet_data)
            
            if response.status_code in [200, 201]:
                data = response.json().get("data", {})
                tweet_id = data.get("id")
                self._increment_rate_limit()
                return PublishResult(success=True, post_id=tweet_id, post_url=f"https://twitter.com/i/web/status/{tweet_id}")
            else:
                error = response.json()
                return PublishResult(success=False, error_message=f"{response.status_code}: {error}")
        except Exception as e:
            return PublishResult(success=False, error_message=str(e))

    def _check_rate_limit(self) -> bool:
        settings = frappe.get_single("Social Settings")
        limit = self.TIER_LIMITS.get(settings.twitter_tier or "Free", 17)
        return (settings.twitter_posts_today or 0) < limit

    def _increment_rate_limit(self):
        settings = frappe.get_single("Social Settings")
        settings.twitter_posts_today = (settings.twitter_posts_today or 0) + 1
        settings.save(ignore_permissions=True)

    def refresh_token(self, integration_name: str = None) -> TokenRefreshResult:
        integration = self.get_integration_doc(integration_name)
        refresh_token = integration.get_password("refresh_token")
        
        if not refresh_token:
            return TokenRefreshResult(success=False, error_message="No refresh token")
        
        try:
            response = requests.post("https://api.twitter.com/2/oauth2/token",
                data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": self.client_id},
                auth=(self.client_id, self.client_secret))
            
            if response.status_code == 200:
                data = response.json()
                integration.access_token = data.get("access_token")
                if data.get("refresh_token"):
                    integration.refresh_token = data.get("refresh_token")
                integration.save(ignore_permissions=True)
                return TokenRefreshResult(success=True, access_token=data.get("access_token"), expires_in=data.get("expires_in"))
            return TokenRefreshResult(success=False, error_message=f"Refresh failed: {response.text}")
        except Exception as e:
            return TokenRefreshResult(success=False, error_message=str(e))

    def fetch_account_analytics(self, integration_name: str = None) -> AnalyticsResult:
        integration = self.get_integration_doc(integration_name)
        access_token = integration.get_password("access_token")
        
        try:
            response = requests.get(f"https://api.twitter.com/2/users/{integration.profile_id}",
                params={"user.fields": "public_metrics"},
                headers={"Authorization": f"Bearer {access_token}"})
            
            if response.status_code == 200:
                metrics = response.json().get("data", {}).get("public_metrics", {})
                return AnalyticsResult(success=True, metrics={
                    "followers_count": metrics.get("followers_count", 0),
                    "following_count": metrics.get("following_count", 0),
                    "posts_count": metrics.get("tweet_count", 0)
                })
            return AnalyticsResult(success=False, error_message="Failed to fetch")
        except Exception as e:
            return AnalyticsResult(success=False, error_message=str(e))

    def fetch_post_analytics(self, post_id: str, integration_name: str = None) -> AnalyticsResult:
        """Note: Non-public metrics require Twitter Pro tier"""
        integration = self.get_integration_doc(integration_name)
        access_token = integration.get_password("access_token")
        
        try:
            response = requests.get(f"https://api.twitter.com/2/tweets/{post_id}",
                params={"tweet.fields": "public_metrics"},
                headers={"Authorization": f"Bearer {access_token}"})
            
            if response.status_code == 200:
                metrics = response.json().get("data", {}).get("public_metrics", {})
                return AnalyticsResult(success=True, metrics={
                    "likes": metrics.get("like_count", 0),
                    "comments": metrics.get("reply_count", 0),
                    "shares": metrics.get("retweet_count", 0),
                    "impressions": metrics.get("impression_count", 0)
                })
            return AnalyticsResult(success=False, error_message="Failed to fetch")
        except Exception as e:
            return AnalyticsResult(success=False, error_message=str(e))

    def get_daily_limit(self) -> int:
        tier = self.settings.twitter_tier or "Free"
        return self.TIER_LIMITS.get(tier, 17)
