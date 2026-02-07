"""
Facebook Page Provider - Meta Graph API v21.0
"""

import os
import frappe
import requests
import time
from frappe_social.frappe_social.providers.base import BaseProvider, PublishResult, AnalyticsResult


class FacebookProvider(BaseProvider):
    PLATFORM = "Facebook"
    MAX_CONTENT_LENGTH = 63206
    SUPPORTS_IMAGES = True
    SUPPORTS_VIDEO = True
    MAX_IMAGES = 10
    MAX_MEDIA_COUNT = 10
    ALLOWS_MULTI_VIDEO = False
    MAX_STORY_BATCH = 10
    DAILY_POST_LIMIT = 200
    ALLOWED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/gif"]
    MAX_IMAGE_SIZE = 8 * 1024 * 1024  # 8 MB
    ALLOWED_VIDEO_TYPES = ["video/mp4", "video/quicktime"]
    MAX_VIDEO_SIZE = 4000 * 1024 * 1024  # 4 GB
    STORY_MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100 MB
    STORY_MAX_IMAGE_SIZE = 8 * 1024 * 1024  # 8 MB
    REEL_MAX_VIDEO_SIZE = 1024 * 1024 * 1024  # 1 GB
    REEL_MIN_DURATION = 3  # seconds
    REEL_MAX_DURATION = 90  # seconds

    def __init__(self, integration_name: str = None):
        super().__init__(integration_name)
        self.api_version = self.settings.meta_api_version or "v21.0"
        self.api_base = f"https://graph.facebook.com/{self.api_version}"

    def _get_full_path(self, file_path: str) -> str:
        """Get absolute local file path from Frappe file URL"""
        if not file_path:
            raise ValueError("Empty file path")
        file_path = file_path.strip()
        mappings = (
            ("/private/files/", ("private", "files")),
            ("/public/files/", ("public", "files")),
            ("/files/", ("public", "files")),
        )
        for prefix, site_path in mappings:
            if file_path.startswith(prefix):
                relative = file_path[len(prefix) :]
                return frappe.get_site_path(*site_path, relative)
        return frappe.get_site_path(file_path.lstrip("/"))

    def _get_public_url(self, file_path: str) -> str:
        """Get publicly accessible URL"""
        if file_path.startswith("http"):
            return file_path
        return frappe.utils.get_url(file_path)

    def _map_cta(self, cta_type: str):
        """Map CTA types to Facebook format"""
        mapping = {
            "Buy Now": "BUY_NOW",
            "Shop Now": "SHOP_NOW",
            "Order Now": "ORDER_NOW",
            "Learn More": "LEARN_MORE",
            "Sign Up": "SIGN_UP",
            "Book Now": "BOOK_NOW",
            "Download": "DOWNLOAD",
            "Contact Us": "CONTACT_US",
        }
        return mapping.get(cta_type)

    def _is_video(self, file_path: str) -> bool:
        """Check if file is a video"""
        return file_path.lower().endswith((".mp4", ".mov", ".avi", ".mkv"))

    def _is_image(self, file_path: str) -> bool:
        """Check if file is an image"""
        return file_path.lower().endswith((".jpg", ".jpeg", ".png", ".gif"))

    def publish_post(
        self, content: str = None, media_files: list = None, scheduled_time=None, **kwargs
    ) -> PublishResult:
        """
        Main publish method that routes to appropriate handler based on content type
        """
        if not self.integration:
            return PublishResult(success=False, error_message="No integration configured")

        page_token = self.integration.get_password("page_access_token")
        page_id = self.integration.page_id
        if not page_token or not page_id:
            return PublishResult(success=False, error_message="Missing page credentials")

        # Determine content type from kwargs
        is_story = kwargs.get("is_story", False)
        is_reel = kwargs.get("is_reel", False)

        media_files = media_files or []

        try:
            # Route to appropriate handler
            if is_story:
                return self._publish_story(content, media_files, page_token, page_id)
            elif is_reel:
                return self._publish_reel(content, media_files, page_token, page_id)
            else:
                return self._publish_feed_post(
                    content, media_files, page_token, page_id, scheduled_time, **kwargs
                )
        except Exception as e:
            frappe.log_error(
                title="Facebook Publish Error",
                message=f"Error: {str(e)}\nTraceback: {frappe.get_traceback()}",
            )
            return PublishResult(success=False, error_message=str(e))

    def _publish_story(self, content: str, media_files: list, page_token: str, page_id: str) -> PublishResult:
        """
        Publish Facebook Page Story (24-hour content)
        Stories support: single image or single video
        """
        if not media_files or len(media_files) != 1:
            return PublishResult(
                success=False, error_message="Stories require exactly one media file (photo or video)"
            )

        file_doc = media_files[0]
        file_url = getattr(file_doc, "file_url", None) or file_doc

        try:
            if self._is_video(file_url):
                return self._publish_video_story(file_url, page_token, page_id)
            elif self._is_image(file_url):
                return self._publish_photo_story(file_url, page_token, page_id)
            else:
                return PublishResult(
                    success=False, error_message="Unsupported media type for story (use JPG/PNG/GIF or MP4)"
                )
        except Exception as e:
            frappe.log_error(
                title="Facebook Story Error",
                message=f"Story publish failed: {str(e)}\n{frappe.get_traceback()}",
            )
            return PublishResult(success=False, error_message=f"Story creation failed: {str(e)}")

    def _publish_photo_story(self, file_url: str, page_token: str, page_id: str) -> PublishResult:
        """Publish photo story - two step process"""
        try:
            full_path = self._get_full_path(file_url)

            # Check file exists and is readable
            if not os.path.exists(full_path):
                return PublishResult(success=False, error_message=f"File not found: {full_path}")

            # Step 1: Upload photo (unpublished)
            with open(full_path, "rb") as f:
                upload_resp = requests.post(
                    f"{self.api_base}/{page_id}/photos",
                    files={"source": f},
                    data={"published": "false", "access_token": page_token},
                    timeout=60,
                ).json()

            if "id" not in upload_resp:
                return self._handle_error(upload_resp, "Photo upload for story failed")

            photo_id = upload_resp["id"]

            # Step 2: Publish as story
            publish_resp = requests.post(
                f"{self.api_base}/{page_id}/photo_stories",
                data={"photo_id": photo_id, "access_token": page_token},
                timeout=30,
            )

            if publish_resp.status_code != 200:
                return self._handle_error(publish_resp.json(), "Photo story publish failed")

            frappe.logger().info(f"Photo story published successfully with photo_id: {photo_id}")
            post_url = f"https://www.facebook.com/{photo_id}"
            return PublishResult(success=True, post_id=photo_id, post_url=post_url)
        except Exception as e:
            frappe.log_error(
                title="Facebook Photo Story Error", message=f"{str(e)}\n{frappe.get_traceback()}"
            )
            return PublishResult(success=False, error_message=str(e))

    def _publish_video_story(self, file_url: str, page_token: str, page_id: str) -> PublishResult:
        try:
            full_path = self._get_full_path(file_url)

            # Check file exists and is readable
            if not os.path.exists(full_path):
                return PublishResult(success=False, error_message=f"File not found: {full_path}")

            file_size = os.path.getsize(full_path)

            if file_size > self.STORY_MAX_VIDEO_SIZE:
                return PublishResult(success=False, error_message="Story video exceeds 100MB limit")

            # STEP 1: Init session
            start_resp = requests.post(
                f"{self.api_base}/{page_id}/video_stories",
                data={
                    "upload_phase": "start",
                    "access_token": page_token,
                },
                timeout=600,
            )

            if start_resp.status_code != 200:
                return self._handle_error(start_resp.json(), "Video story start failed")

            start_data = start_resp.json()
            video_id = start_data.get("video_id")
            upload_url = start_data.get("upload_url")

            if not video_id or not upload_url:
                return self._handle_error(start_data, "Missing video_id or upload_url in start response")

            # STEP 2: Upload EXACTLY as Meta docs
            with open(full_path, "rb") as f:
                upload_resp = requests.post(
                    upload_url,
                    headers={
                        "Authorization": f"OAuth {page_token}",
                        "offset": "0",  # ⚠️ lowercase
                        "file_size": str(file_size),  # ⚠️ REQUIRED
                    },
                    data=f,  # raw binary
                    timeout=600,
                )

            if upload_resp.status_code != 200:
                frappe.log_error(
                    title="Video Story Upload Failed",
                    message=f"{upload_resp.status_code}\n{upload_resp.text}",
                )
                return PublishResult(success=False, error_message="Video upload failed")

            upload_json = upload_resp.json() if upload_resp.content else {}
            if upload_json.get("success") is not True:
                return self._handle_error(upload_json, "Upload phase failed")

            # STEP 3: Finish
            finish_resp = requests.post(
                f"{self.api_base}/{page_id}/video_stories",
                data={
                    "upload_phase": "finish",
                    "video_id": video_id,
                    "access_token": page_token,
                },
                timeout=600,
            )

            if finish_resp.status_code != 200:
                return self._handle_error(finish_resp.json(), "Video story finish failed")

            post_url = f"https://www.facebook.com/{video_id}"
            return PublishResult(success=True, post_id=video_id, post_url=post_url)
        except Exception as e:
            frappe.log_error(
                title="Facebook Video Story Error", message=f"{str(e)}\n{frappe.get_traceback()}"
            )
            return PublishResult(success=False, error_message=str(e))

    def _publish_reel(self, content: str, media_files: list, page_token: str, page_id: str) -> PublishResult:
        """
        Publish Facebook Reel (short vertical video)
        """
        if not media_files or len(media_files) != 1:
            return PublishResult(success=False, error_message="Reels require exactly one video")

        file_doc = media_files[0]
        file_url = getattr(file_doc, "file_url", None) or file_doc
        if not self._is_video(file_url):
            return PublishResult(success=False, error_message="Reels require video files (.mp4 or .mov)")

        try:
            full_path = self._get_full_path(file_url)

            # Check file exists and is readable
            if not os.path.exists(full_path):
                return PublishResult(success=False, error_message=f"File not found: {full_path}")

            file_size = os.path.getsize(full_path)

            if file_size > self.REEL_MAX_VIDEO_SIZE:
                return PublishResult(
                    success=False,
                    error_message=f"Reel video too large: {file_size / (1024*1024):.2f}MB (max 1GB)",
                )

            with open(full_path, "rb") as f:
                reel_resp = requests.post(
                    f"{self.api_base}/{page_id}/videos",
                    files={"source": f},
                    data={
                        "description": content or "",
                        "access_token": page_token,
                        # Short vertical videos automatically become Reels
                    },
                    timeout=600,
                ).json()

            if "id" not in reel_resp:
                return self._handle_error(reel_resp, "Reel upload failed")

            reel_id = reel_resp["id"]
            post_url = f"https://www.facebook.com/{reel_id}"
            return PublishResult(success=True, post_id=reel_id, post_url=post_url)
        except Exception as e:
            frappe.log_error(title="Facebook Reel Error", message=f"{str(e)}\n{frappe.get_traceback()}")
            return PublishResult(success=False, error_message=f"Reel creation failed: {str(e)}")

    def _publish_feed_post(
        self, content: str, media_files: list, page_token: str, page_id: str, scheduled_time=None, **kwargs
    ) -> PublishResult:
        """
        Publish regular Facebook Feed Post
        Supports: single image, multiple images, single video
        """
        try:
            attached_media = []

            # Handle media files
            for media in media_files or []:
                file_path = getattr(media, "file_url", None) or media
                full_path = self._get_full_path(file_path)

                if self._is_video(file_path):
                    if len(media_files) > 1:
                        return PublishResult(
                            success=False, error_message="Only one video allowed in feed post"
                        )

                    # Upload video directly (publishes immediately)
                    with open(full_path, "rb") as f:
                        video_resp = requests.post(
                            f"{self.api_base}/{page_id}/videos",
                            files={"source": f},
                            data={"description": content or "", "access_token": page_token},
                            timeout=600,
                        ).json()

                    if "id" not in video_resp:
                        return self._handle_error(video_resp, "Video upload failed")

                    video_id = video_resp["id"]
                    post_url = f"https://www.facebook.com/{video_id}"
                    return PublishResult(success=True, post_id=video_id, post_url=post_url)

                # Handle images
                with open(full_path, "rb") as f:
                    img_resp = requests.post(
                        f"{self.api_base}/{page_id}/photos",
                        files={"source": f},
                        data={"published": "false", "access_token": page_token},
                        timeout=60,
                    ).json()

                if "id" not in img_resp:
                    return self._handle_error(img_resp, "Image upload failed")

                attached_media.append({"media_fbid": img_resp["id"]})

            # Create post data
            data = {"access_token": page_token, "message": content or ""}

            # Handle scheduling
            if scheduled_time:
                data.update(
                    {
                        "published": "false",
                        "scheduled_publish_time": int(scheduled_time.timestamp()),
                    }
                )

            # Handle CTA
            cta = kwargs.get("cta")
            link = kwargs.get("link")
            url_build = kwargs.get("url_build")
            final_link = url_build if url_build else link

            if cta and final_link:
                cta_type = self._map_cta(cta)
                if cta_type:
                    if attached_media:
                        data["call_to_action"] = frappe.as_json(
                            {"type": cta_type, "value": {"link": final_link}}
                        )
                    else:
                        data["link"] = final_link

            # Attach media for multi-image posts
            for i, media_item in enumerate(attached_media):
                data[f"attached_media[{i}]"] = frappe.as_json(media_item)

            # Publish post
            post_resp = requests.post(f"{self.api_base}/{page_id}/feed", data=data, timeout=60).json()

            if "id" not in post_resp:
                return self._handle_error(post_resp, "Feed post creation failed")

            post_id = post_resp["id"]
            post_url = f"https://www.facebook.com/{post_id}"
            return PublishResult(success=True, post_id=post_id, post_url=post_url)

        except Exception as e:
            frappe.log_error(title="Facebook Feed Post Error", message=f"{str(e)}\n{frappe.get_traceback()}")
            return PublishResult(success=False, error_message=str(e))

    def _handle_error(self, response_data, context: str):
        """Centralized error handling with detailed logging"""
        try:
            if isinstance(response_data, requests.Response):
                response_data = response_data.json()

            error = response_data.get("error", {})
            msg = error.get("message", "Unknown error")
            code = error.get("code", "N/A")
            subcode = error.get("error_subcode", "N/A")

            full_error = (
                f"{context}\n"
                f"Message: {msg}\n"
                f"Code: {code}\n"
                f"Subcode: {subcode}\n"
                f"Full Response: {response_data}"
            )

            frappe.log_error(title=f"Facebook API Error: {context}", message=full_error)

            return PublishResult(success=False, error_message=f"{context}: {msg} (Code: {code})")
        except Exception:
            frappe.log_error(title=f"Facebook Error Parsing: {context}", message=str(response_data))
            return PublishResult(success=False, error_message=f"{context}: {str(response_data)}")

    def _wait_for_media_processing(self, container_id: str, access_token: str, max_retries=30, delay=5):
        """Helper for media processing (used by Instagram, can be used here if needed)"""
        pass  # Not needed for Facebook direct upload

    def get_daily_limit(self) -> int:
        """Get daily posting limit"""
        return self.DAILY_POST_LIMIT

    def fetch_account_analytics(self, integration_name: str = None) -> AnalyticsResult:
        """Fetch page analytics including engagement metrics"""
        try:
            integration = self.get_integration_doc(integration_name)
        except Exception as e:
            return AnalyticsResult(success=False, error_message=f"Integration not found: {str(e)}")

        page_token = integration.get_password("page_access_token") or integration.get_password("access_token")
        if not page_token:
            return AnalyticsResult(success=False, error_message="Missing page token")
        if not integration.page_id:
            return AnalyticsResult(success=False, error_message="Missing page ID")

        try:
            page_response = requests.get(
                f"{self.api_base}/{integration.page_id}",
                params={
                    "access_token": page_token,
                    "fields": "name,fan_count,followers_count,talking_about_count",
                },
            )
            if page_response.status_code != 200:
                error = page_response.json().get("error", {})
                return AnalyticsResult(success=False, error_message=error.get("message", "Failed"))

            page_data = page_response.json()
            posts_response = requests.get(
                f"{self.api_base}/{integration.page_id}/posts",
                params={
                    "access_token": page_token,
                    "fields": "id,shares,reactions.summary(total_count),comments.summary(total_count)",
                    "limit": 25,
                },
            )

            total_likes, total_comments, total_shares, posts_count = 0, 0, 0, 0
            if posts_response.status_code == 200:
                posts_data = posts_response.json().get("data", [])
                posts_count = len(posts_data)
                for post in posts_data:
                    total_likes += post.get("reactions", {}).get("summary", {}).get("total_count", 0)
                    total_comments += post.get("comments", {}).get("summary", {}).get("total_count", 0)
                    total_shares += post.get("shares", {}).get("count", 0)

            followers = page_data.get("followers_count", 0) or page_data.get("fan_count", 0)

            # Safe engagement calculation - handle division by zero
            if posts_count > 0 and followers > 0:
                engagement_rate = round(
                    (total_likes + total_comments + total_shares) / posts_count / followers * 100,
                    2,
                )
            else:
                engagement_rate = 0

            return AnalyticsResult(
                success=True,
                metrics={
                    "followers_count": page_data.get("followers_count", 0),
                    "fan_count": page_data.get("fan_count", 0),
                    "talking_about_count": page_data.get("talking_about_count", 0),
                    "posts_count": posts_count,
                    "likes": total_likes,
                    "comments": total_comments,
                    "shares": total_shares,
                    "engagement_rate": engagement_rate,
                },
            )
        except Exception as e:
            frappe.log_error(
                message=f"Integration: {integration.name}\nError: {str(e)}",
                title="FB Account Analytics Error",
            )
            return AnalyticsResult(success=False, error_message=str(e))

    def fetch_post_analytics(self, post_id: str, integration_name: str = None) -> AnalyticsResult:
        """Fetch analytics for a specific post - safe for both Post and Video nodes"""
        try:
            integration = self.get_integration_doc(integration_name or self.integration_name)
            page_token = integration.get_password("page_access_token") or integration.get_password(
                "access_token"
            )
            if not page_token:
                return AnalyticsResult(success=False, error_message="Missing token")

            # Step 1: Get basic post data safely
            response = requests.get(
                f"{self.api_base}/{post_id}",
                params={
                    "access_token": page_token,
                    "fields": "id,permalink_url,reactions.summary(total_count),comments.summary(total_count),shares",
                },
            )

            likes = comments = shares = 0
            if response.status_code == 200:
                data = response.json()
                likes = data.get("reactions", {}).get("summary", {}).get("total_count", 0)
                comments = data.get("comments", {}).get("summary", {}).get("total_count", 0)
                # Safely get shares — may be missing on Video nodes
                shares_data = data.get("shares", {})
                if isinstance(shares_data, dict):
                    shares = shares_data.get("count", 0)
                # If 'shares' is missing entirely (common on Video), default to 0
            else:
                error = response.json().get("error", {})
                # If field error, continue with 0 shares
                if error.get("code") == 100 and "shares" in error.get("message", ""):
                    frappe.logger().info(f"Shares field not available for post {post_id} (likely a Video)")
                    shares = 0
                else:
                    return AnalyticsResult(
                        success=False, error_message=error.get("message", "Failed to fetch post data")
                    )

            # Step 2: Get insights (impressions & reach)
            impressions = reach = 0
            try:
                insights_resp = requests.get(
                    f"{self.api_base}/{post_id}/insights",
                    params={"access_token": page_token, "metric": "post_impressions,post_impressions_unique"},
                )
                if insights_resp.status_code == 200:
                    for item in insights_resp.json().get("data", []):
                        value = item.get("values", [{}])[0].get("value", 0)
                        if item["name"] == "post_impressions":
                            impressions = value
                        elif item["name"] == "post_impressions_unique":
                            reach = value
            except Exception as e:
                frappe.logger().warning(f"Insights unavailable for {post_id}: {str(e)}")

            # Calculate engagement rate
            total_engagement = likes + comments + shares
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
                    "shares": shares,
                    "impressions": impressions,
                    "reach": reach,
                    "engagement_rate": engagement_rate,
                },
            )

        except Exception as e:
            frappe.log_error(message=f"Post ID: {post_id}\nError: {str(e)}", title="FB Post Analytics Error")
            return AnalyticsResult(success=False, error_message=str(e))
