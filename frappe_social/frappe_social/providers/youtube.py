"""
YouTube Provider - Data API v3

Quota: 10,000 units/day default
- Video upload: 1,600 units (~6 uploads/day)
- Thumbnails require phone verification
- Shorts: Use 9:16 aspect ratio + ≤60s + #Shorts tag
"""

import frappe
import requests
from frappe_social.frappe_social.providers.base import BaseProvider, PublishResult, AnalyticsResult


class YouTubeProvider(BaseProvider):
    PLATFORM = "YouTube"
    MAX_CONTENT_LENGTH = 5000  # Description limit
    SUPPORTS_VIDEO = True
    UPLOAD_QUOTA_COST = 1600

    def __init__(self, integration_name: str = None):
        super().__init__(integration_name)

    def publish_post(self, title: str = None, description: str = None, media_files: list = None,
            tags: list = None, is_short: bool = False, **kwargs) -> PublishResult:
        """Upload video to YouTube"""
        if not self.integration:
            return PublishResult(success=False, error_message="No integration configured")
        
        if not media_files:
            return PublishResult(success=False, error_message="Video file required")
        
        access_token = self.integration.get_password("access_token")
        
        # Check quota
        if not self._check_quota():
            return PublishResult(success=False, error_message="Daily quota exceeded")
        
        try:
            file_doc = media_files[0]
            file_path = file_doc.file_url if hasattr(file_doc, 'file_url') else file_doc
            full_path = frappe.get_site_path("public", file_path.lstrip("/"))
            
            # Add #Shorts tag if applicable
            video_tags = tags or []
            if is_short and "Shorts" not in video_tags:
                video_tags.append("Shorts")
            
            # Prepare metadata
            metadata = {
                "snippet": {
                    "title": title or "Untitled Video",
                    "description": description or "",
                    "tags": video_tags,
                    "categoryId": "22"  # People & Blogs
                },
                "status": {
                    "privacyStatus": "public",
                    "selfDeclaredMadeForKids": False
                }
            }
            
            # Initiate resumable upload
            init_response = requests.post(
                "https://www.googleapis.com/upload/youtube/v3/videos",
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                    "X-Upload-Content-Type": "video/*"
                },
                json=metadata
            )
            
            if init_response.status_code != 200:
                return PublishResult(success=False, error_message=f"Init failed: {init_response.text}")
            
            upload_url = init_response.headers.get("Location")
            
            # Upload video file
            with open(full_path, "rb") as video_file:
                upload_response = requests.put(upload_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    data=video_file)
            
            if upload_response.status_code == 200:
                video_data = upload_response.json()
                video_id = video_data.get("id")
                self._update_quota(self.UPLOAD_QUOTA_COST)
                return PublishResult(success=True, post_id=video_id, post_url=f"https://www.youtube.com/watch?v={video_id}")
            else:
                return PublishResult(success=False, error_message=f"Upload failed: {upload_response.text}")
                
        except Exception as e:
            return PublishResult(success=False, error_message=str(e))

    def _check_quota(self) -> bool:
        settings = frappe.get_single("Social Settings")
        return (settings.youtube_quota_used or 0) + self.UPLOAD_QUOTA_COST <= (settings.youtube_quota_limit or 10000)

    def _update_quota(self, cost: int):
        settings = frappe.get_single("Social Settings")
        settings.youtube_quota_used = (settings.youtube_quota_used or 0) + cost
        settings.save(ignore_permissions=True)

    def fetch_account_analytics(self, integration_name: str = None) -> AnalyticsResult:
        integration = self.get_integration_doc(integration_name)
        access_token = integration.get_password("access_token")
        
        try:
            response = requests.get("https://www.googleapis.com/youtube/v3/channels",
                params={"access_token": access_token, "part": "statistics", "mine": "true"})
            
            if response.status_code == 200:
                channels = response.json().get("items", [])
                if channels:
                    stats = channels[0].get("statistics", {})
                    return AnalyticsResult(success=True, metrics={
                        "followers_count": int(stats.get("subscriberCount", 0)),
                        "video_views": int(stats.get("viewCount", 0)),
                        "posts_count": int(stats.get("videoCount", 0))
                    })
            return AnalyticsResult(success=False, error_message="Failed to fetch")
        except Exception as e:
            return AnalyticsResult(success=False, error_message=str(e))

    def fetch_post_analytics(self, post_id: str, integration_name: str = None) -> AnalyticsResult:
        integration = self.get_integration_doc(integration_name)
        access_token = integration.get_password("access_token")
        
        try:
            response = requests.get("https://www.googleapis.com/youtube/v3/videos",
                params={"access_token": access_token, "part": "statistics", "id": post_id})
            
            if response.status_code == 200:
                videos = response.json().get("items", [])
                if videos:
                    stats = videos[0].get("statistics", {})
                    return AnalyticsResult(success=True, metrics={
                        "video_views": int(stats.get("viewCount", 0)),
                        "likes": int(stats.get("likeCount", 0)),
                        "comments": int(stats.get("commentCount", 0))
                    })
            return AnalyticsResult(success=False, error_message="Video not found")
        except Exception as e:
            return AnalyticsResult(success=False, error_message=str(e))

    def get_daily_limit(self) -> int:
        return 6  # ~6 video uploads with 10,000 quota
