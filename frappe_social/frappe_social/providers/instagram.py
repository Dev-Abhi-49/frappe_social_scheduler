import frappe
import requests
import time
import os
from frappe_social.frappe_social.providers.base import BaseProvider, PublishResult, AnalyticsResult


class InstagramProvider(BaseProvider):
    PLATFORM = "Instagram"
    MAX_CONTENT_LENGTH = 2200
    SUPPORTS_IMAGES = True
    SUPPORTS_VIDEO = True
    MAX_IMAGES = 10
    DAILY_POST_LIMIT = 25
    ALLOWED_IMAGE_TYPES = ["image/jpeg"]
    MAX_IMAGE_SIZE = 8 * 1024 * 1024  # 8 MB
    ALLOWED_VIDEO_TYPES = ["video/mp4", "video/quicktime"]
    MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100 MB for regular, 1GB for reels
    MAX_MEDIA_COUNT = 10
    ALLOWS_MULTI_VIDEO = False

    # Content type specific limits
    STORY_MAX_VIDEO_SIZE = 100 * 1024 * 1024  # 100 MB
    STORY_MAX_IMAGE_SIZE = 8 * 1024 * 1024  # 8 MB
    REEL_MAX_VIDEO_SIZE = 1024 * 1024 * 1024  # 1 GB
    REEL_MIN_DURATION = 3  # seconds
    REEL_MAX_DURATION = 90  # seconds

    def __init__(self, integration_name: str = None):
        super().__init__(integration_name)
        self.api_version = self.settings.meta_api_version or "v21.0"
        self.api_base = f"https://graph.facebook.com/{self.api_version}"

    def publish_post(self, content: str = None, media_files: list = None, **kwargs) -> PublishResult:
        """
        Main publish method that routes to appropriate handler based on content type
        """
        if not self.integration:
            return PublishResult(success=False, error_message="No integration configured")

        page_token = self.integration.get_password("page_access_token")
        ig_user_id = self.integration.profile_id

        if not page_token or not ig_user_id:
            return PublishResult(success=False, error_message="Missing credentials")

        # Determine content type from kwargs
        is_story = kwargs.get("is_story", False)
        is_reel = kwargs.get("is_reel", False)
        is_post = kwargs.get("is_post", True)  # Default to regular post

        try:
            # Route to appropriate handler
            if is_story:
                return self._publish_story(content, media_files, page_token, ig_user_id)
            elif is_reel:
                return self._publish_reel(content, media_files, page_token, ig_user_id)
            else:
                return self._publish_feed_post(content, media_files, page_token, ig_user_id)

        except Exception as e:
            frappe.log_error(title="Instagram Publish Error", message=f"{str(e)}\n{frappe.get_traceback()}")
            return PublishResult(success=False, error_message=str(e))

    def _publish_story(
        self, content: str, media_files: list, page_token: str, ig_user_id: str
    ) -> PublishResult:
        """
        Publish Instagram Story (24-hour content)
        Stories support: single image or single video
        """
        if not media_files or len(media_files) == 0:
            return PublishResult(success=False, error_message="Stories require media (image or video)")

        if len(media_files) > 1:
            return PublishResult(success=False, error_message="Stories support only one media file at a time")

        file_doc = media_files[0]
        file_url = file_doc.file_url if hasattr(file_doc, "file_url") else file_doc

        try:
            if self._is_video(file_url):
                return self._publish_video_story(file_url, page_token, ig_user_id)
            elif self._is_image(file_url):
                return self._publish_image_story(file_url, page_token, ig_user_id)
            else:
                return PublishResult(success=False, error_message="Unsupported media type for story")

        except Exception as e:
            return PublishResult(success=False, error_message=f"Story creation failed: {str(e)}")

    def _publish_image_story(self, file_url: str, page_token: str, ig_user_id: str) -> PublishResult:
        """Publish image story"""
        # Convert PNG to JPEG if needed
        if file_url.lower().endswith(".png"):
            file_url = self._convert_png_to_jpeg(file_url)

        public_url = self._get_public_url(file_url)

        # Create story container
        story_data = {
            "image_url": public_url,
            "media_type": "STORIES",
            "access_token": page_token,
        }

        res = requests.post(f"{self.api_base}/{ig_user_id}/media", data=story_data, timeout=30)

        if res.status_code != 200:
            return self._handle_error(res, "Story container creation failed")

        container_id = res.json().get("id")

        # Wait for image processing (even images need a moment)
        if not self._wait_for_media_processing(container_id, page_token, max_retries=20, delay=2):
            return PublishResult(success=False, error_message="Story image processing timeout")

        # Publish the story
        return self._publish_container(container_id, page_token, ig_user_id, "Story")

    def _publish_video_story(self, file_url: str, page_token: str, ig_user_id: str) -> PublishResult:
        """Publish video story"""
        local_path = self._get_local_file_path(file_url)
        file_size = os.path.getsize(local_path)

        # Validate file size
        if file_size > self.STORY_MAX_VIDEO_SIZE:
            return PublishResult(
                success=False,
                error_message=f"Story video too large: {file_size / (1024*1024):.2f}MB (max 100MB)",
            )

        # Initialize video story upload
        init_data = {
            "media_type": "STORIES",
            "video_url": self._get_public_url(file_url),
            "access_token": page_token,
        }

        init_res = requests.post(f"{self.api_base}/{ig_user_id}/media", data=init_data, timeout=30)

        if init_res.status_code != 200:
            return self._handle_error(init_res, "Story video container creation failed")

        container_id = init_res.json().get("id")

        # Wait for processing
        if not self._wait_for_media_processing(container_id, page_token, max_retries=60, delay=5):
            return PublishResult(success=False, error_message="Story video processing timeout")

        # Publish the story
        return self._publish_container(container_id, page_token, ig_user_id, "Story")

    def _publish_reel(
        self, content: str, media_files: list, page_token: str, ig_user_id: str
    ) -> PublishResult:
        """
        Publish Instagram Reel
        Reels: Video content (3-90 seconds)
        """
        if not media_files or len(media_files) == 0:
            return PublishResult(success=False, error_message="Reels require a video file")

        if len(media_files) > 1:
            return PublishResult(success=False, error_message="Reels support only one video at a time")

        file_doc = media_files[0]
        file_url = file_doc.file_url if hasattr(file_doc, "file_url") else file_doc

        if not self._is_video(file_url):
            return PublishResult(success=False, error_message="Reels require video files (.mp4 or .mov)")

        local_path = self._get_local_file_path(file_url)
        file_size = os.path.getsize(local_path)

        # Validate file size (Reels can be up to 1GB)
        if file_size > self.REEL_MAX_VIDEO_SIZE:
            return PublishResult(
                success=False,
                error_message=f"Reel video too large: {file_size / (1024*1024):.2f}MB (max 1GB)",
            )

        try:
            # Initialize Reel upload
            init_data = {
                "media_type": "REELS",
                "video_url": self._get_public_url(file_url),
                "caption": content or "",
                "share_to_feed": "true",  # Also share to main feed
                "access_token": page_token,
            }

            init_res = requests.post(f"{self.api_base}/{ig_user_id}/media", data=init_data, timeout=60)

            if init_res.status_code != 200:
                return self._handle_error(init_res, "Reel container creation failed")

            container_id = init_res.json().get("id")

            # Wait for video processing (Reels take longer)
            if not self._wait_for_media_processing(container_id, page_token, max_retries=120, delay=6):
                return PublishResult(success=False, error_message="Reel processing timeout (>12 minutes)")

            # Publish the reel
            return self._publish_container(container_id, page_token, ig_user_id, "Reel")

        except Exception as e:
            return PublishResult(success=False, error_message=f"Reel creation failed: {str(e)}")

    def _publish_feed_post(
        self, content: str, media_files: list, page_token: str, ig_user_id: str
    ) -> PublishResult:
        """
        Publish regular Instagram Feed Post
        Supports: single image, single video, or carousel (multiple images)
        """
        if not media_files:
            return PublishResult(success=False, error_message="Instagram feed posts require media")

        try:
            container_id = None
            is_carousel = len(media_files) > 1

            # CAROUSEL (Multiple Images)
            if is_carousel:
                child_container_ids = []

                for media_item in media_files:
                    file_url = media_item.file_url if hasattr(media_item, "file_url") else media_item

                    if not self._is_image(file_url):
                        return PublishResult(
                            success=False, error_message="Carousels currently support images only"
                        )

                    if file_url.lower().endswith(".png"):
                        file_url = self._convert_png_to_jpeg(file_url)

                    public_url = self._get_public_url(file_url)

                    item_data = {
                        "image_url": public_url,
                        "is_carousel_item": "true",
                        "access_token": page_token,
                    }

                    res = requests.post(f"{self.api_base}/{ig_user_id}/media", data=item_data, timeout=60)

                    if res.status_code != 200:
                        return self._handle_error(res, "Carousel item creation failed")

                    item_container_id = res.json().get("id")

                    # Wait for each carousel item to be ready
                    if not self._wait_for_media_processing(
                        item_container_id, page_token, max_retries=15, delay=2
                    ):
                        return PublishResult(
                            success=False,
                            error_message=f"Carousel item {len(child_container_ids)+1} processing timeout",
                        )

                    child_container_ids.append(item_container_id)

                # Create carousel parent container
                carousel_data = {
                    "media_type": "CAROUSEL",
                    "children": ",".join(child_container_ids),
                    "caption": content or "",
                    "access_token": page_token,
                }

                parent_res = requests.post(
                    f"{self.api_base}/{ig_user_id}/media", data=carousel_data, timeout=60
                )

                if parent_res.status_code != 200:
                    return self._handle_error(parent_res, "Carousel parent creation failed")

                container_id = parent_res.json().get("id")

            # SINGLE MEDIA (Image or Video)
            else:
                file_doc = media_files[0]
                file_url = file_doc.file_url if hasattr(file_doc, "file_url") else file_doc

                if self._is_video(file_url):
                    # Single video post
                    public_url = self._get_public_url(file_url)

                    video_data = {
                        "media_type": "VIDEO",
                        "video_url": public_url,
                        "caption": content or "",
                        "access_token": page_token,
                    }

                    res = requests.post(f"{self.api_base}/{ig_user_id}/media", data=video_data, timeout=30)

                    if res.status_code != 200:
                        return self._handle_error(res, "Video container creation failed")

                    container_id = res.json().get("id")

                    # Wait for video processing
                    if not self._wait_for_media_processing(container_id, page_token, max_retries=60, delay=6):
                        return PublishResult(success=False, error_message="Video processing timeout")

                else:
                    # Single image post
                    if file_url.lower().endswith(".png"):
                        file_url = self._convert_png_to_jpeg(file_url)

                    public_url = self._get_public_url(file_url)

                    image_data = {
                        "image_url": public_url,
                        "caption": content or "",
                        "access_token": page_token,
                    }

                    res = requests.post(f"{self.api_base}/{ig_user_id}/media", data=image_data, timeout=30)

                    if res.status_code != 200:
                        return self._handle_error(res, "Image container creation failed")

                    container_id = res.json().get("id")

            # Publish the container
            return self._publish_container(container_id, page_token, ig_user_id, "Post")

        except Exception as e:
            frappe.log_error(title="Instagram Feed Post Error", message=f"{str(e)}\n{frappe.get_traceback()}")
            return PublishResult(success=False, error_message=str(e))

    def _publish_container(
        self, container_id: str, page_token: str, ig_user_id: str, content_type: str
    ) -> PublishResult:
        """
        Final step: Publish the created container
        """
        publish_data = {
            "creation_id": container_id,
            "access_token": page_token,
        }

        publish_res = requests.post(
            f"{self.api_base}/{ig_user_id}/media_publish", data=publish_data, timeout=30
        )

        if publish_res.status_code == 200:
            post_id = publish_res.json().get("id")
            post_url = f"https://www.instagram.com/p/{post_id}/" if post_id else None

            return PublishResult(
                success=True,
                post_id=post_id,
                post_url=post_url,
            )
        else:
            return self._handle_error(publish_res, f"{content_type} publish failed")

    def _is_video(self, url):
        """Check if file is a video"""
        return url.lower().endswith((".mp4", ".mov"))

    def _is_image(self, url):
        """Check if file is an image"""
        return url.lower().endswith((".jpg", ".jpeg", ".png"))

    def _wait_for_media_processing(self, container_id, access_token, max_retries=30, delay=5):
        """
        Wait for Instagram to process the video/media
        Returns True when finished, False on error or timeout
        """
        url = f"{self.api_base}/{container_id}"
        params = {"fields": "status_code,status", "access_token": access_token}

        for attempt in range(max_retries):
            try:
                res = requests.get(url, params=params, timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    code = data.get("status_code")
                    status = data.get("status")

                    frappe.logger().info(
                        f"[Instagram] Media processing attempt {attempt + 1}/{max_retries}: "
                        f"Container {container_id} - Status: {code} ({status})"
                    )

                    if code == "FINISHED":
                        frappe.logger().info(
                            f"[Instagram] Media {container_id} processing completed successfully"
                        )
                        return True

                    if code == "ERROR":
                        error_msg = data.get("status", "Unknown error during processing")
                        frappe.log_error(
                            title="Instagram Media Processing Error",
                            message=f"Container: {container_id}\n"
                            f"Status: {status}\n"
                            f"Error: {error_msg}\n"
                            f"Response: {res.text}",
                        )
                        return False

                    # Status is still IN_PROGRESS or EXPIRED, continue waiting
                    if code in ["IN_PROGRESS", "PUBLISHED"]:
                        time.sleep(delay)
                        continue

                    # Unknown status code
                    frappe.logger().warning(
                        f"[Instagram] Unknown status code '{code}' for container {container_id}"
                    )

                else:
                    frappe.logger().warning(
                        f"[Instagram] Status check failed: HTTP {res.status_code} - {res.text}"
                    )

            except requests.exceptions.Timeout:
                frappe.logger().error(f"[Instagram] Timeout checking status for {container_id}")
            except Exception as e:
                frappe.logger().error(f"[Instagram] Error checking media status: {str(e)}")

            time.sleep(delay)

        # Timeout reached
        frappe.log_error(
            title="Instagram Processing Timeout",
            message=f"Container {container_id} did not finish processing after "
            f"{max_retries * delay} seconds ({max_retries} retries)",
        )
        return False

    def _handle_error(self, response, context):
        """Handle API errors with detailed logging"""
        try:
            err = response.json().get("error", {})
            msg = err.get("message", "Unknown error")
            code = err.get("code")
            subcode = err.get("error_subcode")

            full_error = (
                f"{context}\n"
                f"Message: {msg}\n"
                f"Code: {code}\n"
                f"Subcode: {subcode}\n"
                f"Full Response: {response.text}"
            )

            frappe.log_error(
                title=f"Instagram API Error: {context}",
                message=full_error,
            )

            return PublishResult(
                success=False,
                error_message=f"{context}: {msg} (Code: {code}, Subcode: {subcode})",
            )
        except Exception as e:
            return PublishResult(
                success=False,
                error_message=f"{context}: HTTP {response.status_code} - {response.text}",
            )

    def _get_local_file_path(self, file_url):
        """Get the absolute local file path"""
        if file_url.startswith("/private"):
            return frappe.get_site_path(file_url.strip("/"))

        clean_path = file_url.strip("/")
        if clean_path.startswith("files/"):
            clean_path = clean_path[6:]

        return frappe.get_site_path("public", "files", clean_path)

    def _convert_png_to_jpeg(self, file_path: str) -> str:
        """Convert PNG to JPEG (Instagram requirement)"""
        from PIL import Image
        import uuid

        local_path = self._get_local_file_path(file_path)

        with Image.open(local_path) as img:
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")

            filename = f"ig_{uuid.uuid4().hex}.jpg"
            output_path = frappe.get_site_path("public", "files", filename)
            img.save(output_path, "JPEG", quality=95)

        return f"/files/{filename}"

    def _get_public_url(self, file_path: str) -> str:
        """Get publicly accessible URL for the file"""
        if file_path.startswith("http"):
            return file_path

        if file_path.startswith("/private"):
            frappe.throw(
                "Instagram requires public files. Please ensure your files are not in private folder."
            )

        return frappe.utils.get_url(file_path)

    def fetch_account_analytics(self, integration_name: str = None) -> AnalyticsResult:
        """Fetch account-level analytics"""
        return AnalyticsResult(success=False, error_message="Instagram analytics not yet implemented")

    def fetch_post_analytics(self, post_id: str, integration_name: str = None) -> AnalyticsResult:
        """Fetch post-level analytics"""
        return AnalyticsResult(success=False, error_message="Instagram post analytics not yet implemented")

    def get_daily_limit(self) -> int:
        """Get daily posting limit"""
        return self.DAILY_POST_LIMIT
