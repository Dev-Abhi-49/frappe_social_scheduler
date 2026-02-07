"""
LinkedIn Provider - Uses Posts API (UGC deprecated)

Requirements:
- Monthly versioned API headers (LinkedIn-Version: YYYYMM)
- X-Restli-Protocol-Version: 2.0.0 header required
- 150 requests/day per member
"""

import frappe
import requests
from frappe_social.frappe_social.providers.base import BaseProvider, PublishResult, AnalyticsResult


class LinkedInProvider(BaseProvider):
    PLATFORM = "LinkedIn"
    MAX_CONTENT_LENGTH = 3000
    SUPPORTS_IMAGES = True
    SUPPORTS_VIDEO = True

    def __init__(self, integration_name: str = None):
        super().__init__(integration_name)
        self.api_version = self.settings.linkedin_api_version or "202501"

    def _get_headers(self):
        token = self.integration.get_password("access_token") if self.integration else None
        return {
            "Authorization": f"Bearer {token}",
            "LinkedIn-Version": self.api_version,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json"
        }

    def publish_post(self, content: str = None, media_files: list = None, **kwargs) -> PublishResult:
        if not self.integration:
            return PublishResult(success=False, error_message="No integration configured")
        
        author = f"urn:li:person:{self.integration.profile_id}"
        
        post_data = {
            "author": author,
            "lifecycleState": "PUBLISHED",
            "visibility": "PUBLIC",
            "commentary": content or "",
            "distribution": {"feedDistribution": "MAIN_FEED"}
        }
        
        try:
            response = requests.post("https://api.linkedin.com/rest/posts",
                headers=self._get_headers(), json=post_data)
            
            if response.status_code in [200, 201]:
                post_id = response.headers.get("x-restli-id") or response.json().get("id", "")
                return PublishResult(success=True, post_id=post_id, post_url=f"https://www.linkedin.com/feed/update/{post_id}")
            else:
                error = response.json() if response.text else {}
                return PublishResult(success=False, error_message=f"{response.status_code}: {error.get('message', response.text)}")
        except Exception as e:
            return PublishResult(success=False, error_message=str(e))

    def fetch_account_analytics(self, integration_name: str = None) -> AnalyticsResult:
        """LinkedIn personal analytics not available via API"""
        return AnalyticsResult(success=True, metrics={"note": "Personal analytics not available via LinkedIn API"})

    def fetch_post_analytics(self, post_id: str, integration_name: str = None) -> AnalyticsResult:
        return AnalyticsResult(success=True, metrics={"note": "Post analytics not available for personal posts"})

    def get_daily_limit(self) -> int:
        return 150
