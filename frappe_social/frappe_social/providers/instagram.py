"""
Instagram Provider - Meta Graph API v24.0
"""

import os
import time
import shutil  # Added this import
import frappe
import requests
import subprocess
import json
from pathlib import Path
from frappe_social.frappe_social.providers.base import BaseProvider, PublishResult, AnalyticsResult
from frappe import _
from frappe_social.frappe_social.utils.media import (
    get_full_path,
    get_video_duration,
    get_video_dimensions,
    is_video,
    copy_to_public_temp,
    cleanup_temp_files,
    get_public_url,
)

class InstagramProvider(BaseProvider):
    PLATFORM = "Instagram"
    MAX_CONTENT_LENGTH = 2200
    
    SUPPORTS_IMAGES = True
    SUPPORTS_VIDEO = True
    
    MAX_IMAGES = 10  # For carousel

    DAILY_POST_LIMIT = 25  # Instagram API limit (can be up to 100 for some accounts)
    ALLOWS_MULTI_VIDEO = True  # Carousel can have videos
    
    ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png"]
    ALLOWED_VIDEO_TYPES = ["video/mp4", "video/quicktime"]
    
    MAX_IMAGE_SIZE = 8 * 1024 * 1024  # 8 MB
    MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100 MB
    MAX_VIDEO_DURATION = 60
    
    MAX_STORY_BATCH = 10
    STORY_MAX_IMAGE_SIZE = 8 * 1024 * 1024  # 8 MB
    STORY_MAX_VIDEO_SIZE = 100 * 1024 * 1024 # 100 MB
    STORY_MAX_DURATION = 60  # seconds
    
    REEL_MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100 MB 
    REEL_MIN_DURATION = 3  # seconds
    REEL_MAX_DURATION = 60 # seconds

    def __init__(self, integration_name: str = None):
        super().__init__(integration_name)
        self.api_version = self.settings.meta_api_version or "v24.0"
        self.api_base = f"https://graph.facebook.com/{self.api_version}"
        self._temp_public_files = []  # Initialize cleanup list

    def publish_post(
        self, content: str = None, media_files: list = None, scheduled_time=None, **kwargs
    ) -> PublishResult:
        """Main publish method that routes to appropriate handler based on content type"""
        if not self.integration:
            return PublishResult(success=False, error_message="No integration configured")

        page_token = self.integration.get_password("page_access_token")
        instagram_id = self.integration.profile_id

        if not page_token or not instagram_id:
            return PublishResult(success=False, error_message="Missing Instagram credentials")

        # Determine content type from kwargs
        is_ig_story = kwargs.get("is_ig_story", False)
        is_ig_reel = kwargs.get("is_ig_reel", False)

        media_files = media_files or []

        try:
            # Route to appropriate handler
            if is_ig_reel:
                return self._publish_reel(content, media_files, page_token, instagram_id, **kwargs)
            elif is_ig_story:
                return self._publish_story(content, media_files, page_token, instagram_id, **kwargs)
            else:
                return self._publish_feed_post(content, media_files, page_token, instagram_id, **kwargs)

        except Exception as e:
            # Cleanup on any error
            cleanup_temp_files(self._temp_public_files)
            frappe.log_error(
                title="Instagram Publish Error",
                message=f"Error: {str(e)}\nTraceback: {frappe.get_traceback()}",
            )
            return PublishResult(success=False, error_message=str(e))

    def _publish_feed_post(
        self, content: str, media_files: list, page_token: str, instagram_id: str, **kwargs
    ) -> PublishResult:
        """Publish Instagram Feed Post"""
        try:
            if not media_files or len(media_files) == 0:
                return PublishResult(success=False, error_message="Instagram requires at least one media file")

            # Single media (image or video)
            if len(media_files) == 1:
                return self._publish_single_media(content, media_files[0], page_token, instagram_id, **kwargs)

            # Carousel (2-10 items)
            if len(media_files) > self.MAX_IMAGES:
                return PublishResult(
                    success=False, 
                    error_message=f"Instagram allows max 10 items in carousel (got {len(media_files)})"
                )

            return self._publish_carousel(content, media_files, page_token, instagram_id)

        except Exception as e:
            cleanup_temp_files(self._temp_public_files)  # Added cleanup
            frappe.log_error(title="Instagram Feed Post Error", message=f"{str(e)}\n{frappe.get_traceback()}")
            return PublishResult(success=False, error_message=str(e))

    def _publish_single_media(
        self, content: str, media_file, page_token: str, instagram_id: str, **kwargs
    ) -> PublishResult:
        """Publish single image or video to Instagram feed"""
        try:
            file_url = getattr(media_file, "file_url", None) or media_file
            public_url = get_public_url(file_url, self._temp_public_files)  # Get public URL and track for cleanup
            # is_video = self._is_video(file_url)

            # # INSTAGRAM API CHANGE: All single videos must be published as REELS
            # if is_video:
            #     frappe.logger().info(
            #         "Instagram API requires videos to be published as Reels. "
            #         "Auto-converting to Reel with share_to_feed enabled."
            #     )
            #     kwargs["is_feed_video"] = True
            #     kwargs["share_to_feed"] = True
                
            #     return self._publish_reel(
            #         content=content,
            #         media_files=[media_file],
            #         page_token=page_token,
            #         instagram_id=instagram_id,
            #         **kwargs
            #     )

            # Images use standard feed post workflow
            container_data = {
                "access_token": page_token,
                "caption": content or "",
                "image_url": public_url
            }

            container_resp = requests.post(
                f"{self.api_base}/{instagram_id}/media",
                data=container_data,
                timeout=300, 
            ).json()

            if "id" not in container_resp:
                cleanup_temp_files(self._temp_public_files)  # Added cleanup
                return self._handle_error(container_resp, "Container creation failed")

            container_id = container_resp["id"]
            
            frappe.logger().info(f"Waiting for image container {container_id} to be ready...")
            processing_result = self._wait_for_media_processing(
                container_id, 
                page_token, 
                max_retries=20,  # Images process faster than videos
                delay=3          # Check every 3 seconds
            )
            
            if not processing_result["success"]:
                cleanup_temp_files(self._temp_public_files)
                return PublishResult(
                    success=False,
                    error_message=f"Image processing failed: {processing_result['message']}"
                )

            # Publish container
            publish_resp = requests.post(
                f"{self.api_base}/{instagram_id}/media_publish",
                data={"creation_id": container_id, "access_token": page_token},
                timeout=300,
            ).json()

            if "id" not in publish_resp:
                cleanup_temp_files(self._temp_public_files)  # Added cleanup
                return self._handle_error(publish_resp, "Publishing failed")

            media_id = publish_resp["id"]
            
            # Get permalink
            permalink = self._get_media_permalink(media_id, page_token)
            post_url = permalink or f"https://www.instagram.com/p/{media_id}"

            # Cleanup temp files after successful publish
            cleanup_temp_files(self._temp_public_files)
            
            return PublishResult(success=True, post_id=media_id, post_url=post_url)

        except Exception as e:
            cleanup_temp_files(self._temp_public_files)  # Added cleanup
            frappe.log_error(title="Instagram Single Media Error", message=f"{str(e)}\n{frappe.get_traceback()}")
            return PublishResult(success=False, error_message=str(e))

    def _publish_carousel(
        self, content: str, media_files: list, page_token: str, instagram_id: str
    ) -> PublishResult:
        """Publish carousel post (2-10 images/videos)"""
        try:
            item_container_ids = []

            # STEP 1: Create item containers
            for media_file in media_files:
                file_url = getattr(media_file, "file_url", None) or media_file
                public_url = get_public_url(file_url, self._temp_public_files)  # Track temp files for cleanup
                is_video_file = is_video(file_url)

                item_data = {
                    "access_token": page_token,
                    "is_carousel_item": "true",
                }

                if is_video_file:
                    item_data["media_type"] = "VIDEO"
                    item_data["video_url"] = public_url
                else:
                    item_data["image_url"] = public_url

                item_resp = requests.post(
                    f"{self.api_base}/{instagram_id}/media",
                    data=item_data,
                    timeout=300,
                ).json()

                if "id" not in item_resp:
                    cleanup_temp_files(self._temp_public_files)  # Added cleanup
                    return self._handle_error(item_resp, f"Carousel item creation failed for {file_url}")

                item_id = item_resp["id"]

                # Wait for video processing if needed
                if is_video_file:
                    processing_result = self._wait_for_media_processing(item_id, page_token, max_retries=40, delay=5)
                    if not processing_result["success"]:
                        cleanup_temp_files(self._temp_public_files)  # Added cleanup
                        return PublishResult(
                            success=False,
                            error_message=f"Video processing failed for carousel item: {processing_result['message']}",
                        )

                item_container_ids.append(item_id)

            # STEP 2: Create carousel container
            carousel_data = {
                "access_token": page_token,
                "media_type": "CAROUSEL",
                "caption": content or "",
                "children": ",".join(item_container_ids),
            }

            carousel_resp = requests.post(
                f"{self.api_base}/{instagram_id}/media",
                data=carousel_data,
                timeout=300,
            ).json()

            if "id" not in carousel_resp:
                cleanup_temp_files(self._temp_public_files)  # Added cleanup
                return self._handle_error(carousel_resp, "Carousel container creation failed")

            carousel_id = carousel_resp["id"]

            # STEP 3: Publish carousel
            publish_resp = requests.post(
                f"{self.api_base}/{instagram_id}/media_publish",
                data={"creation_id": carousel_id, "access_token": page_token},
                timeout=300,
            ).json()

            if "id" not in publish_resp:
                cleanup_temp_files(self._temp_public_files)  # Added cleanup
                return self._handle_error(publish_resp, "Carousel publishing failed")

            media_id = publish_resp["id"]
            
            # Get permalink
            permalink = self._get_media_permalink(media_id, page_token)
            post_url = permalink or f"https://www.instagram.com/p/{media_id}"

            # Cleanup temp files after successful publish
            cleanup_temp_files(self._temp_public_files)
            
            return PublishResult(success=True, post_id=media_id, post_url=post_url)

        except Exception as e:
            cleanup_temp_files(self._temp_public_files)  # Added cleanup
            frappe.log_error(title="Instagram Carousel Error", message=f"{str(e)}\n{frappe.get_traceback()}")
            return PublishResult(success=False, error_message=str(e))

    def _publish_reel(
        self, content: str, media_files: list, page_token: str, instagram_id: str, **kwargs
    ) -> PublishResult:
        """Publish Instagram Reel"""
        if not media_files or len(media_files) != 1:
            return PublishResult(success=False, error_message="Reels require exactly one video")

        file_doc = media_files[0]
        file_url = getattr(file_doc, "file_url", None) or file_doc

        if not is_video(file_url):
            return PublishResult(success=False, error_message="Reels require video files (.mp4 or .mov)")

        try:
            full_path = get_full_path(file_url)

            if not os.path.exists(full_path):
                return PublishResult(success=False, error_message=f"File not found: {full_path}")

            file_size = os.path.getsize(full_path)

            if file_size > self.REEL_MAX_VIDEO_SIZE:
                return PublishResult(
                    success=False,
                    error_message=f"Video too large: {file_size / (1024*1024):.2f}MB (max 1GB)",
                )

            # Check if this is a feed video (relaxed validation) or explicit reel
            is_feed_video = kwargs.get("is_feed_video", False)

            # Validate duration
            try:
                duration = get_video_duration(full_path)
                
                if not is_feed_video:
                    if duration < self.REEL_MIN_DURATION or duration > self.REEL_MAX_DURATION:
                        return PublishResult(
                            success=False,
                            error_message=(
                                f"Reel duration must be {self.REEL_MIN_DURATION}–{self.REEL_MAX_DURATION} seconds "
                                f"(got {duration:.1f}s)"
                            ),
                        )
                else:
                    if duration > self.REEL_MAX_DURATION:
                        frappe.logger().warning(
                            f"Feed video duration ({duration:.1f}s) exceeds recommended Reel limit "
                            f"({self.REEL_MAX_DURATION}s). Attempting to publish anyway."
                        )
            except Exception as e:
                frappe.logger().warning(f"Could not validate video duration: {str(e)}")

            # # Validate aspect ratio (warn only)
            # try:
            #     width, height = get_video_dimensions(full_path)
            #     if height <= width:
            #         frappe.logger().warning(
            #             f"Video is not vertical (got {width}x{height}). "
            #             "Vertical 9:16 aspect ratio is recommended for Reels."
            #         )
            # except Exception as e:
            #     frappe.logger().warning(f"Could not validate video dimensions: {str(e)}")

            public_url = get_public_url(file_url, self._temp_public_files)  # Track temp files for cleanup

            # STEP 1: Create reel container
            container_data = {
                "access_token": page_token,
                "media_type": "REELS",
                "video_url": public_url,
                "caption": content or "",
            }
            
            # Share to feed by default
            share_to_feed = kwargs.get("share_to_feed", True)
            container_data["share_to_feed"] = "true" if share_to_feed else "false"

            # Optional: Add thumbnail offset
            thumb_offset = kwargs.get("thumb_offset")
            if thumb_offset is not None:
                container_data["thumb_offset"] = int(thumb_offset)

            container_resp = requests.post(
                f"{self.api_base}/{instagram_id}/media",
                data=container_data,
                timeout=300,
            ).json()

            if "id" not in container_resp:
                cleanup_temp_files(self._temp_public_files)  # Added cleanup
                return self._handle_error(container_resp, "Reel container creation failed")

            container_id = container_resp["id"]

            # STEP 2: Wait for video processing
            processing_result = self._wait_for_media_processing(
                container_id, page_token, max_retries=60, delay=10
            )
            if not processing_result["success"]:
                cleanup_temp_files(self._temp_public_files)  # Added cleanup
                return PublishResult(
                    success=False, error_message=f"Video processing failed: {processing_result['message']}"
                )

            # STEP 3: Publish reel
            publish_resp = requests.post(
                f"{self.api_base}/{instagram_id}/media_publish",
                data={"creation_id": container_id, "access_token": page_token},
                timeout=300,
            ).json()

            if "id" not in publish_resp:
                cleanup_temp_files(self._temp_public_files)  # Added cleanup
                return self._handle_error(publish_resp, "Reel publishing failed")

            media_id = publish_resp["id"]
            
            # Get permalink
            permalink = self._get_media_permalink(media_id, page_token)
            post_url = permalink or f"https://www.instagram.com/reel/{media_id}"

            # Cleanup temp files after successful publish
            cleanup_temp_files(self._temp_public_files)
            
            return PublishResult(success=True, post_id=media_id, post_url=post_url)

        except Exception as e:
            cleanup_temp_files(self._temp_public_files)  # Added cleanup
            frappe.log_error(title="Instagram Reel Error", message=f"{str(e)}\n{frappe.get_traceback()}")
            return PublishResult(success=False, error_message=f"Reel creation failed: {str(e)}")

    def _publish_story(
        self, content: str, media_files: list, page_token: str, instagram_id: str, **kwargs
    ) -> PublishResult:
        """Publish Instagram Story (24-hour content)"""
        if not media_files or len(media_files) == 0:
            return PublishResult(
                success=False, error_message="Stories require at least one media file (photo or video)"
            )

        if len(media_files) > 1:
            return PublishResult(
                success=False, error_message="Instagram stories support only one media file at a time"
            )

        file_doc = media_files[0]
        file_url = getattr(file_doc, "file_url", None) or file_doc

        try:
            full_path = get_full_path(file_url)

            if not os.path.exists(full_path):
                return PublishResult(success=False, error_message=f"File not found: {full_path}")

            is_video_file = is_video(file_url)
            public_url = get_public_url(file_url, self._temp_public_files)  # Track temp files for cleanup

            # Validate file size and duration
            file_size = os.path.getsize(full_path)

            if is_video_file:
                if file_size > self.STORY_MAX_VIDEO_SIZE:
                    return PublishResult(success=False, error_message="Story video exceeds 100MB limit")

                try:
                    duration = get_video_duration(full_path)
                    if duration > self.STORY_MAX_DURATION:
                        return PublishResult(
                            success=False, error_message=f"Story videos must be ≤60s (got {duration:.1f}s)"
                        )
                except Exception as e:
                    frappe.logger().warning(f"Could not validate story video duration: {str(e)}")

                # try:
                #     width, height = get_video_dimensions(full_path)
                #     if height <= width:
                #         frappe.logger().warning(
                #             f"Story video is not vertical (got {width}x{height}). Vertical 9:16 recommended."
                #         )
                # except Exception as e:
                #     frappe.logger().warning(f"Could not validate story video dimensions: {str(e)}")
            else:
                if file_size > self.STORY_MAX_IMAGE_SIZE:
                    return PublishResult(success=False, error_message="Story image exceeds 8MB limit")

            # STEP 1: Create story container
            container_data = {
                "access_token": page_token,
                "media_type": "STORIES",
            }

            if is_video_file:
                container_data["video_url"] = public_url
            else:
                container_data["image_url"] = public_url

            container_resp = requests.post(
                f"{self.api_base}/{instagram_id}/media",
                data=container_data,
                timeout=240,
            ).json()

            if "id" not in container_resp:
                cleanup_temp_files(self._temp_public_files)  # Added cleanup
                return self._handle_error(container_resp, "Story container creation failed")

            container_id = container_resp["id"]

            # STEP 2: Wait for processing (if video)
            if is_video_file:
                processing_result = self._wait_for_media_processing(container_id, page_token, max_retries=40, delay=5)
                if not processing_result["success"]:
                    cleanup_temp_files(self._temp_public_files)  # Added cleanup
                    return PublishResult(
                        success=False, error_message=f"Story processing failed: {processing_result['message']}"
                    )

            # STEP 3: Publish story
            publish_resp = requests.post(
                f"{self.api_base}/{instagram_id}/media_publish",
                data={"creation_id": container_id, "access_token": page_token},
                timeout=240,
            ).json()

            if "id" not in publish_resp:
                cleanup_temp_files(self._temp_public_files)  # Added cleanup
                return self._handle_error(publish_resp, "Story publishing failed")

            story_id = publish_resp["id"]
            
            # Get permalink
            permalink = self._get_media_permalink(story_id, page_token)
            post_url = permalink or f"https://www.instagram.com/stories/{instagram_id}/{story_id}"

            # Cleanup temp files after successful publish
            cleanup_temp_files(self._temp_public_files)
            
            return PublishResult(success=True, post_id=story_id, post_url=post_url)

        except Exception as e:
            cleanup_temp_files(self._temp_public_files)  # Added cleanup
            frappe.log_error(title="Instagram Story Error", message=f"{str(e)}\n{frappe.get_traceback()}")
            return PublishResult(success=False, error_message=f"Story creation failed: {str(e)}")

    def _wait_for_media_processing(
        self, container_id: str, access_token: str, max_retries=30, delay=5
    ) -> dict:
        """Poll Instagram media container status until processing is complete"""
        for attempt in range(max_retries):
            try:
                status_resp = requests.get(
                    f"{self.api_base}/{container_id}",
                    params={"access_token": access_token, "fields": "status_code"},
                    timeout=120,
                ).json()

                status_code = status_resp.get("status_code")

                if status_code == "FINISHED":
                    return {"success": True, "message": "Processing complete"}
                elif status_code == "ERROR":
                    error_msg = status_resp.get("error_message", "Unknown error")
                    return {"success": False, "message": f"Processing error: {error_msg}"}
                elif status_code in ["EXPIRED", "PUBLISHED"]:
                    return {"success": False, "message": f"Invalid status: {status_code}"}

                frappe.logger().info(f"Container {container_id} status: {status_code}, retrying in {delay}s...")
                time.sleep(delay)

            except Exception as e:
                frappe.logger().error(f"Status check failed: {str(e)}")
                time.sleep(delay)

        return {"success": False, "message": f"Timeout after {max_retries * delay}s waiting for processing"}

    def _get_media_permalink(self, media_id: str, access_token: str) -> str:
        """Get the actual permalink/URL for the published media"""
        try:
            media_resp = requests.get(
                f"{self.api_base}/{media_id}",
                params={"access_token": access_token, "fields": "permalink"},
                timeout=120,
            ).json()
            
            return media_resp.get("permalink")
        except Exception as e:
            frappe.logger().warning(f"Could not fetch permalink for {media_id}: {str(e)}")
            return None

    def _handle_error(self, response_data, context: str):
        """Centralized error handling with detailed logging"""
        try:
            if isinstance(response_data, requests.Response):
                response_data = response_data.json()

            error = response_data.get("error", {})
            msg = error.get("message", "Unknown error")
            code = error.get("code", "N/A")
            subcode = error.get("error_subcode", "N/A")
            user_msg = error.get("error_user_msg", "")

            full_error = (
                f"{context}\n"
                f"Message: {msg}\n"
                f"Code: {code}\n"
                f"Subcode: {subcode}\n"
                f"User Message: {user_msg}\n"
                f"Full Response: {response_data}"
            )

            frappe.log_error(title=f"Instagram API Error: {context}", message=full_error)

            error_display = user_msg if user_msg else f"{msg} (Code: {code})"
            return PublishResult(success=False, error_message=f"{context}: {error_display}")
            
        except Exception:
            frappe.log_error(title=f"Instagram Error Parsing: {context}", message=str(response_data))
            return PublishResult(success=False, error_message=f"{context}: {str(response_data)}")

    def get_daily_limit(self) -> int:
        """Get daily posting limit"""
        return self.DAILY_POST_LIMIT

    def fetch_account_analytics(self, integration_name: str = None) -> AnalyticsResult:
        """Fetch Instagram account analytics including engagement metrics"""
        try:
            integration = self.get_integration_doc(integration_name)
        except Exception as e:
            return AnalyticsResult(success=False, error_message=f"Integration not found: {str(e)}")

        page_token = integration.get_password("page_access_token") or integration.get_password("access_token")
        if not page_token:
            return AnalyticsResult(success=False, error_message="Missing access token")
        if not integration.profile_id:
            return AnalyticsResult(success=False, error_message="Missing Instagram ID")

        try:
            # Get account info
            account_response = requests.get(
                f"{self.api_base}/{integration.profile_id}",
                params={
                    "access_token": page_token,
                    "fields": "username,followers_count,follows_count,media_count",
                },
                timeout=120,
            )

            if account_response.status_code != 200:
                error = account_response.json().get("error", {})
                return AnalyticsResult(success=False, error_message=error.get("message", "Failed"))

            account_data = account_response.json()

            # Get recent media for engagement calculation
            media_response = requests.get(
                f"{self.api_base}/{integration.profile_id}/media",
                params={
                    "access_token": page_token,
                    "fields": "id,media_type,like_count,comments_count",
                    "limit": 25,
                },
                timeout=120,
            )

            total_likes, total_comments, posts_count = 0, 0, 0
            if media_response.status_code == 200:
                media_data = media_response.json().get("data", [])
                posts_count = len(media_data)
                for post in media_data:
                    total_likes += post.get("like_count", 0)
                    total_comments += post.get("comments_count", 0)

            followers = account_data.get("followers_count", 0)

            # Calculate engagement rate
            if posts_count > 0 and followers > 0:
                engagement_rate = round((total_likes + total_comments) / posts_count / followers * 100, 2)
            else:
                engagement_rate = 0

            return AnalyticsResult(
                success=True,
                metrics={
                    "followers_count": followers,
                    "follows_count": account_data.get("follows_count", 0),
                    "media_count": account_data.get("media_count", 0),
                    "posts_count": posts_count,
                    "likes": total_likes,
                    "comments": total_comments,
                    "engagement_rate": engagement_rate,
                },
            )
        except Exception as e:
            frappe.log_error(
                message=f"Integration: {integration.name}\nError: {str(e)}",
                title="Instagram Account Analytics Error",
            )
            return AnalyticsResult(success=False, error_message=str(e))

    def fetch_post_analytics(self, post_id: str, integration_name: str = None) -> AnalyticsResult:
        """Fetch analytics for a specific Instagram post"""
        try:
            integration = self.get_integration_doc(integration_name or self.integration_name)
            page_token = integration.get_password("page_access_token") or integration.get_password("access_token")
            if not page_token:
                return AnalyticsResult(success=False, error_message="Missing token")

            # Get basic post data
            response = requests.get(
                f"{self.api_base}/{post_id}",
                params={
                    "access_token": page_token,
                    "fields": "id,media_type,permalink,like_count,comments_count",
                },
                timeout=120,
            )

            likes = comments = 0
            if response.status_code == 200:
                data = response.json()
                likes = data.get("like_count", 0)
                comments = data.get("comments_count", 0)
            else:
                error = response.json().get("error", {})
                return AnalyticsResult(success=False, error_message=error.get("message", "Failed to fetch post data"))

            # Get insights
            impressions = reach = saved = 0
            try:
                insights_resp = requests.get(
                    f"{self.api_base}/{post_id}/insights",
                    params={"access_token": page_token, "metric": "impressions,reach,saved,engagement"},
                    timeout=120,
                )
                if insights_resp.status_code == 200:
                    for item in insights_resp.json().get("data", []):
                        value = item.get("values", [{}])[0].get("value", 0)
                        metric_name = item["name"]
                        if metric_name == "impressions":
                            impressions = value
                        elif metric_name == "reach":
                            reach = value
                        elif metric_name == "saved":
                            saved = value
            except Exception as e:
                frappe.logger().warning(f"Insights unavailable for {post_id}: {str(e)}")

            # Calculate engagement rate
            total_engagement = likes + comments + saved
            if reach > 0:
                engagement_rate = round((total_engagement / reach) * 100, 2)
            elif impressions > 0:
                engagement_rate = round((total_engagement / impressions) * 100, 2)
            else:
                engagement_rate = 0

            return AnalyticsResult(
                success=True,
                metrics={
                    "likes": likes,
                    "comments": comments,
                    "saved": saved,
                    "impressions": impressions,
                    "reach": reach,
                    "engagement_rate": engagement_rate,
                },
            )

        except Exception as e:
            frappe.log_error(message=f"Post ID: {post_id}\nError: {str(e)}", title="Instagram Post Analytics Error")
            return AnalyticsResult(success=False, error_message=str(e))
