"""
YouTube Provider - Data API v3

Quota: 10,000 units/day default
- Video upload: 1,600 units (~6 uploads/day)
- Community post: 50 units
- Thumbnail upload: 50 units (requires phone verification)
- Shorts: Use 9:16 aspect ratio + ≤60s + #Shorts tag
"""

import frappe
import requests
import os
from datetime import datetime, timezone
from frappe_social.frappe_social.providers.base import BaseProvider, PublishResult, AnalyticsResult
from frappe_social.frappe_social.api.oauth import auto_refresh_if_expired
from frappe_social.frappe_social.utils.media import get_full_path

class YouTubeProvider(BaseProvider):
    PLATFORM = "YouTube"
    MAX_CONTENT_LENGTH = 5000
    
    SUPPORTS_IMAGES = True
    SUPPORTS_VIDEO = True
    
    # Quota costs
    VIDEO_UPLOAD_QUOTA_COST = 1600
    COMMUNITY_POST_QUOTA_COST = 50
    THUMBNAIL_UPLOAD_QUOTA_COST = 50
    
    MAX_VIDEO = 1
    MAX_IMAGES = 10
    
    ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/jpg", "image/gif"]
    ALLOWED_VIDEO_TYPES = ["video/mp4", "video/mov"]
    
    DAILY_QUOTA_LIMIT = 10000
    ALLOWS_MULTI_VIDEO = False
    ALLOWS_MULTI_IMAGE = True
    
    MAX_IMAGE_SIZE = 8 * 1024 * 1024  # 8MB for community posts
    MAX_VIDEO_SIZE = 256 * 1024 * 1024 * 1024  # 256GB
    MAX_VIDEO_DURATION = 12 * 60 * 60  # 12 hours
    MAX_THUMBNAIL_SIZE = 2 * 1024 * 1024  # 2MB

    def __init__(self, integration_name: str = None):
        super().__init__(integration_name)
        
    def _get_valid_access_token(self):
        """Ensure we have a fresh access token (YouTube tokens expire after ~1 hour)"""
        if not auto_refresh_if_expired(self.integration):
            raise Exception("Failed to refresh YouTube access token. "
                            "Please reconnect the account or check Social Settings.")
        return self.integration.get_password("access_token")

    def publish_post(self, content: str = None, media_files: list = None, video_title: str = None,
                     tags: str = None, is_short: bool = False, is_video: bool = False, 
                     is_yt_post: bool = False, thumbnail: str = None, privacy_status: str = "public",
                     scheduled_time: str = None, video_category: str = "22", **kwargs) -> PublishResult:
        """
        Publish content to YouTube
        - is_yt_post: Community post (text + images)
        - is_short: Short video (≤60s, vertical)
        - is_video: Regular video
        """
        if not self.integration:
            return PublishResult(success=False, error_message="No integration configured")

        try:
            access_token = self._get_valid_access_token()
        except Exception as e:
            return PublishResult(success=False, error_message=str(e))
        
        # Route to appropriate handler
        if is_yt_post:
            return self._publish_community_post(content, media_files, access_token)
        elif is_short or is_video:
            return self._publish_video(
                content=content,
                media_files=media_files,
                video_title=video_title,
                tags=tags,
                is_short=is_short,
                thumbnail=thumbnail,
                privacy_status=privacy_status,
                scheduled_time=scheduled_time,
                video_category=video_category,
                access_token=access_token
            )
        else:
            return PublishResult(success=False, error_message="Please specify content type: is_yt_post, is_short, or is_video")

    def _publish_community_post(self, content: str, media_files: list, access_token: str) -> PublishResult:
        """Publish a YouTube Community Post (text + images)"""
        
        # Check quota
        if not self._check_quota(self.COMMUNITY_POST_QUOTA_COST):
            return PublishResult(success=False, error_message="Daily quota exceeded for community posts")
        
        try:
            # Prepare post body
            post_body = {
                "snippet": {
                    "text": content or ""
                }
            }
            
            # If media files are provided, upload them first
            media_ids = []
            if media_files and len(media_files) > 0:
                for media_file in media_files:
                    media_id = self._upload_community_image(media_file, access_token)
                    if media_id:
                        media_ids.append(media_id)
                
                # Add media references to post
                if media_ids:
                    post_body["snippet"]["media"] = {
                        "images": [{"id": img_id} for img_id in media_ids]
                    }
            
            # Create community post
            response = requests.post(
                "https://www.googleapis.com/youtube/v3/posts",
                params={"part": "snippet"},
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                },
                json=post_body
            )
            
            if response.status_code == 200 or response.status_code == 201:
                post_data = response.json()
                post_id = post_data.get("id")
                
                # Update quota
                self._update_quota(self.COMMUNITY_POST_QUOTA_COST)
                
                # Community posts don't have a direct URL in API response
                # URL format: https://www.youtube.com/post/{post_id}
                post_url = f"https://www.youtube.com/post/{post_id}" if post_id else None
                
                return PublishResult(
                    success=True, 
                    post_id=post_id, 
                    post_url=post_url
                )
            else:
                error_message = self._parse_error(response)
                return PublishResult(success=False, error_message=error_message)
                
        except Exception as e:
            frappe.log_error(f"YouTube Community Post Error: {str(e)}", "YouTube Provider")
            return PublishResult(success=False, error_message=str(e))

    def _upload_community_image(self, media_file, access_token: str) -> str:
        """Upload an image for community post and return media ID"""
        try:
            file_path = media_file.file_url if hasattr(media_file, 'file_url') else media_file
            full_path = get_full_path(file_path)
            
            # Upload image
            with open(full_path, "rb") as image_file:
                files = {"file": image_file}
                response = requests.post(
                    "https://www.googleapis.com/upload/youtube/v3/images",
                    params={"uploadType": "media"},
                    headers={"Authorization": f"Bearer {access_token}"},
                    files=files
                )
            
            if response.status_code == 200:
                image_data = response.json()
                return image_data.get("id")
            else:
                frappe.log_error(f"Image upload failed: {response.text}", "YouTube Provider")
                return None
                
        except Exception as e:
            frappe.log_error(f"Image upload error: {str(e)}", "YouTube Provider")
            return None

    def _publish_video(self, content: str, media_files: list, video_title: str, tags: str,
                       is_short: bool, thumbnail: str, privacy_status: str, scheduled_time: str,
                       video_category: str, access_token: str, social_post_name: str = None,**kwargs) -> PublishResult:
        """Upload video (Short or regular) to YouTube"""
        
        if not media_files or len(media_files) == 0:
            return PublishResult(success=False, error_message="Video file required")
        
        # Check quota
        total_quota_needed = self.VIDEO_UPLOAD_QUOTA_COST
        if thumbnail:
            total_quota_needed += self.THUMBNAIL_UPLOAD_QUOTA_COST
        
        if not self._check_quota(total_quota_needed):
            return PublishResult(success=False, error_message=f"Daily quota exceeded (need {total_quota_needed} units)")
        
        try:     
            visibility_setting = None
            made_for_kids_setting = None
            
            if social_post_name:
                try:
                    post_config = frappe.db.get_value(
                        "Social Post",
                        social_post_name,
                        ["visibility", "made_for_kids", "age_restriction"],
                        as_dict=1
                    )
                    if post_config:
                        visibility_setting = post_config.get("visibility")
                        made_for_kids_setting = post_config.get("made_for_kids")
                        # age_restriction is stored for reference but cannot be set via API
                except Exception as e:
                    frappe.log_error(f"Failed to fetch post config: {str(e)}", "YouTube Provider")
            
            # Map visibility from UI values (Public/Unlisted/Private) to API values (public/unlisted/private)
            if visibility_setting:
                privacy_status = visibility_setting.strip().lower()
            
            # Map made_for_kids from UI values (Yes/No) to boolean
            self_declared_made_for_kids = False
            if made_for_kids_setting:
                self_declared_made_for_kids = (made_for_kids_setting.strip().lower() == "yes")
            
            file_doc = media_files[0]
            file_path = file_doc.file_url if hasattr(file_doc, 'file_url') else file_doc
            full_path = get_full_path(file_path)
                        
            # Parse tags
            video_tags = self._parse_tags(tags)
            
            # Add #Shorts tag for shorts
            if is_short:
                if "Shorts" not in video_tags and "#Shorts" not in video_tags:
                    video_tags.append("Shorts")
                
                # Also add to description if not present
                description = content or ""
                if "#Shorts" not in description and "#shorts" not in description.lower():
                    description = f"{description}\n\n#Shorts" if description else "#Shorts"
                content = description
            
            # Prepare metadata
            metadata = {
                "snippet": {
                    "title": video_title or "Untitled Video",
                    "description": content or "",
                    "tags": video_tags[:500],  # YouTube allows max 500 tags
                    "categoryId": str(video_category),
                    "defaultLanguage": "en",
                    "defaultAudioLanguage": "en"
                },
                "status": {
                    "privacyStatus": privacy_status,
                    "selfDeclaredMadeForKids": self_declared_made_for_kids,
                    "embeddable": True,
                    "publicStatsViewable": True
                }
            }
            
            # Add scheduled time if provided
            if scheduled_time:
                # Convert to ISO 8601 format if needed
                if isinstance(scheduled_time, str):
                    try:
                        dt = frappe.utils.get_datetime(scheduled_time)
                        scheduled_time_iso = dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
                        metadata["status"]["publishAt"] = scheduled_time_iso
                        metadata["status"]["privacyStatus"] = "private"  # Must be private for scheduled
                    except Exception as e:
                        frappe.log_error(f"Schedule time parsing error: {str(e)}", "YouTube Provider")
            
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
                error_message = self._parse_error(init_response)
                return PublishResult(success=False, error_message=f"Upload initialization failed: {error_message}")
            
            upload_url = init_response.headers.get("Location")
            if not upload_url:
                return PublishResult(success=False, error_message="No upload URL received from YouTube")
            
            # Upload video file with chunked upload for better reliability
            video_id = self._upload_video_file(full_path, upload_url, access_token)
            
            if not video_id:
                return PublishResult(success=False, error_message="Video upload failed - no video ID returned")
            
            # Update quota for video upload
            self._update_quota(self.VIDEO_UPLOAD_QUOTA_COST)
            
            # Upload thumbnail if provided
            if thumbnail:
                thumbnail_success = self._upload_thumbnail(video_id, thumbnail, access_token)
                if thumbnail_success:
                    self._update_quota(self.THUMBNAIL_UPLOAD_QUOTA_COST)
            
            # Generate appropriate URL
            if is_short:
                post_url = f"https://www.youtube.com/shorts/{video_id}"
            else:
                post_url = f"https://www.youtube.com/watch?v={video_id}"
            
            return PublishResult(
                success=True, 
                post_id=video_id, 
                post_url=post_url
            )
                
        except Exception as e:
            frappe.log_error(f"YouTube Video Upload Error: {str(e)}", "YouTube Provider")
            return PublishResult(success=False, error_message=str(e))

    def _upload_video_file(self, file_path: str, upload_url: str, access_token: str) -> str:
        """Upload video file using resumable upload"""
        try:
            file_size = os.path.getsize(file_path)
            chunk_size = 10 * 1024 * 1024  # 10MB chunks
            
            with open(file_path, "rb") as video_file:
                # For files larger than 10MB, use chunked upload
                if file_size > chunk_size:
                    return self._chunked_upload(video_file, upload_url, access_token, file_size, chunk_size)
                else:
                    # Simple upload for small files
                    upload_response = requests.put(
                        upload_url,
                        headers={"Authorization": f"Bearer {access_token}"},
                        data=video_file
                    )
                    
                    if upload_response.status_code == 200 or upload_response.status_code == 201:
                        video_data = upload_response.json()
                        return video_data.get("id")
                    else:
                        frappe.log_error(f"Video upload failed: {upload_response.text}", "YouTube Provider")
                        return None
                        
        except Exception as e:
            frappe.log_error(f"Video file upload error: {str(e)}", "YouTube Provider")
            return None

    def _chunked_upload(self, video_file, upload_url: str, access_token: str, file_size: int, chunk_size: int) -> str:
        """Upload large video in chunks with resume capability"""
        try:
            offset = 0
            
            while offset < file_size:
                chunk = video_file.read(chunk_size)
                chunk_length = len(chunk)
                
                headers = {
                    "Authorization": f"Bearer {access_token}",
                    "Content-Length": str(chunk_length),
                    "Content-Range": f"bytes {offset}-{offset + chunk_length - 1}/{file_size}"
                }
                
                response = requests.put(upload_url, headers=headers, data=chunk)
                
                if response.status_code == 200 or response.status_code == 201:
                    # Upload complete
                    video_data = response.json()
                    return video_data.get("id")
                elif response.status_code == 308:
                    # Resume incomplete, continue
                    offset += chunk_length
                else:
                    frappe.log_error(f"Chunk upload failed: {response.text}", "YouTube Provider")
                    return None
            
            return None
            
        except Exception as e:
            frappe.log_error(f"Chunked upload error: {str(e)}", "YouTube Provider")
            return None

    def _upload_thumbnail(self, video_id: str, thumbnail_path: str, access_token: str) -> bool:
        """Upload custom thumbnail for video"""
        try:
            full_thumbnail_path = get_full_path(thumbnail_path)
            
            if not os.path.exists(full_thumbnail_path):
                frappe.log_error(f"Thumbnail not found: {full_thumbnail_path}", "YouTube Provider")
                return False
            
            # Check file size
            thumbnail_size = os.path.getsize(full_thumbnail_path)
            if thumbnail_size > self.MAX_THUMBNAIL_SIZE:
                frappe.log_error(f"Thumbnail too large: {thumbnail_size} bytes", "YouTube Provider")
                return False
            
            with open(full_thumbnail_path, "rb") as thumb_file:
                response = requests.post(
                    f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set",
                    params={"videoId": video_id},
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Content-Type": "image/jpeg"
                    },
                    data=thumb_file
                )
            
            if response.status_code == 200:
                return True
            else:
                frappe.log_error(f"Thumbnail upload failed: {response.text}", "YouTube Provider")
                return False
                
        except Exception as e:
            frappe.log_error(f"Thumbnail upload error: {str(e)}", "YouTube Provider")
            return False

    def _parse_tags(self, tags) -> list:
        """Parse tags from string or list"""
        if not tags:
            return []
        
        if isinstance(tags, list):
            return [str(tag).strip() for tag in tags if tag]
        
        if isinstance(tags, str):
            # Handle comma-separated, newline-separated, or space-separated
            if ',' in tags:
                return [tag.strip() for tag in tags.split(',') if tag.strip()]
            elif '\n' in tags:
                return [tag.strip() for tag in tags.split('\n') if tag.strip()]
            else:
                # Single tag or space-separated
                return [tag.strip() for tag in tags.split() if tag.strip()]
        
        return []

    def _parse_error(self, response) -> str:
        """Parse YouTube API error response"""
        try:
            error_data = response.json()
            if "error" in error_data:
                error = error_data["error"]
                if "message" in error:
                    return f"{error.get('code', 'Error')}: {error['message']}"
                return str(error)
            return response.text
        except:
            return f"HTTP {response.status_code}: {response.text}"

    def _check_quota(self, required_quota: int = 0) -> bool:
        """Check if enough quota is available"""
        settings = frappe.get_single("Social Settings")
        
        # Reset quota if it's a new day
        today = frappe.utils.today()
        if settings.youtube_quota_reset_date != today:
            settings.youtube_quota_used = 0
            settings.youtube_quota_reset_date = today
            settings.save(ignore_permissions=True)
        
        current_quota = settings.youtube_quota_used or 0
        quota_limit = settings.youtube_quota_limit or self.DAILY_QUOTA_LIMIT
        
        return (current_quota + required_quota) <= quota_limit

    def _update_quota(self, cost: int):
        """Update quota usage"""
        settings = frappe.get_single("Social Settings")
        settings.youtube_quota_used = (settings.youtube_quota_used or 0) + cost
        settings.save(ignore_permissions=True)

    def fetch_account_analytics(self, integration_name: str = None) -> AnalyticsResult:
        """Fetch channel statistics"""
        integration = self.get_integration_doc(integration_name)
        
        if not auto_refresh_if_expired(integration):
            return AnalyticsResult(success=False, error_message="Failed to refresh access token")
        
        access_token = integration.get_password("access_token")
        
        try:
            response = requests.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={
                    "access_token": access_token, 
                    "part": "statistics,snippet", 
                    "mine": "true"
                }
            )
            
            if response.status_code == 200:
                channels = response.json().get("items", [])
                if channels:
                    stats = channels[0].get("statistics", {})
                    snippet = channels[0].get("snippet", {})
                    
                    return AnalyticsResult(success=True, metrics={
                        "channel_name": snippet.get("title", ""),
                        "subscribers": int(stats.get("subscriberCount", 0)),
                        "total_views": int(stats.get("viewCount", 0)),
                        "total_videos": int(stats.get("videoCount", 0)),
                        "followers_count": int(stats.get("subscriberCount", 0)),  # Compatibility
                        "posts_count": int(stats.get("videoCount", 0))  # Compatibility
                    })
            
            error_message = self._parse_error(response)
            return AnalyticsResult(success=False, error_message=error_message)
            
        except Exception as e:
            frappe.log_error(f"Analytics fetch error: {str(e)}", "YouTube Provider")
            return AnalyticsResult(success=False, error_message=str(e))

    def fetch_post_analytics(self, post_id: str, integration_name: str = None) -> AnalyticsResult:
        """Fetch video statistics"""
        integration = self.get_integration_doc(integration_name)
        
        if not auto_refresh_if_expired(integration):
            return AnalyticsResult(success=False, error_message="Failed to refresh access token")
        access_token = integration.get_password("access_token")
        
        try:
            response = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "access_token": access_token, 
                    "part": "statistics,snippet", 
                    "id": post_id
                }
            )
            
            if response.status_code == 200:
                videos = response.json().get("items", [])
                if videos:
                    stats = videos[0].get("statistics", {})
                    snippet = videos[0].get("snippet", {})
                    
                    return AnalyticsResult(success=True, metrics={
                        "title": snippet.get("title", ""),
                        "views": int(stats.get("viewCount", 0)),
                        "likes": int(stats.get("likeCount", 0)),
                        "comments": int(stats.get("commentCount", 0)),
                        "favorites": int(stats.get("favoriteCount", 0)),
                        "video_views": int(stats.get("viewCount", 0))  # Compatibility
                    })
            
            error_message = self._parse_error(response)
            return AnalyticsResult(success=False, error_message=error_message)
            
        except Exception as e:
            frappe.log_error(f"Post analytics error: {str(e)}", "YouTube Provider")
            return AnalyticsResult(success=False, error_message=str(e))

    def get_daily_limit(self) -> int:
        """Get estimated daily upload limit based on quota"""
        return self.DAILY_QUOTA_LIMIT // self.VIDEO_UPLOAD_QUOTA_COST  # ~6 videos per day
