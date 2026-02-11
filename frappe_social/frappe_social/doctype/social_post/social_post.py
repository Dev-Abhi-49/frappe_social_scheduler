# social_post.py - Updated validation section

import frappe
from frappe import _
import subprocess, json
import os
from frappe.model.document import Document
from frappe_social.frappe_social.utils.media import normalize_file_type


class SocialPost(Document):

    VALID_TRANSITIONS = {
        "Draft": ["Scheduled", "Publishing", "Cancelled"],
        "Scheduled": ["Publishing", "Draft", "Cancelled"],
        "Publishing": ["Published", "Partially Published", "Failed"],
        "Published": [],
        "Partially Published": ["Publishing"],
        "Failed": ["Scheduled", "Publishing", "Cancelled"],
        "Cancelled": ["Draft"],
    }

    MAX_RETRIES = 3

    def before_save(self):
        """Handle defaults before saving"""
        # For Instagram, ensure at least one content type is selected
        if self.platform == "Instagram":
            if not (self.is_ig_post or self.is_ig_reel or self.is_ig_story):
                return None

        # For Facebook, ensure at least one content type is selected
        elif self.platform == "Facebook":
            if not (self.is_fb_post or self.is_fb_reel or self.is_fb_story):
                return None

    def validate(self):
        """Validate the post before saving/submitting"""
        # 1. Fix media metadata first
        self.fix_media_metadata()

        # 2. Platform-specific validations
        if self.platform == "Facebook":
            self.validate_facebook_content()
        elif self.platform == "Instagram":
            self.validate_instagram_content()
        elif self.platform == "YouTube":
            self.validate_youtube_content()
            
        elif self.platform == "LinkedIn":
            pass
        elif self.platform == "Twitter":
            pass
        else:
            frappe.throw(_("Unsupported platform: {0}").format(self.platform))

        # 3. General validations
        self.validate_content_length()
        self.validate_media()
        
    def fix_media_metadata(self):
        """Fix media metadata (file type and size)"""
        if not self.media:
            return

        for item in self.media:
            if not item.file:
                continue

            db_file = frappe.db.get_value(
                "File",
                {"file_url": item.file},
                ["file_type", "file_size"],
                as_dict=True,
            )

            item.file_size = (db_file.file_size if db_file else item.file_size) or 0
            item.file_type = normalize_file_type(
                item.file,
                (db_file.file_type if db_file else item.file_type),
            )
            
    def _get_full_path(self, file_path: str) -> str:
        """Get absolute local file path - consistent with provider logic"""
        if not file_path:
            raise ValueError("Empty file path")
        
        file_path = file_path.strip()
        
        # Handle Frappe's file path conventions
        mappings = (
            ("/private/files/", ("private", "files")),
            ("/public/files/", ("public", "files")),
            ("/files/", ("public", "files")),
        )
        
        for prefix, site_path in mappings:
            if file_path.startswith(prefix):
                relative = file_path[len(prefix):]
                return frappe.get_site_path(*site_path, relative)
        
        return frappe.get_site_path(file_path.lstrip("/"))
            
    def _get_video_duration(self, path: str) -> float:
        if not os.path.exists(path):
            frappe.throw(_("File not found: {0}").format(path))

        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            data = json.loads(result.stdout)
            duration = float(data.get("format", {}).get("duration", 0))
            
            if duration <= 0:
                frappe.throw(_("Could not determine video duration"))
                
            return duration
        
        except Exception as e:
            frappe.throw(_("Error reading video duration: {0}").format(str(e)))


    def _get_video_dimensions(self, path: str) -> tuple:
        """Get video width and height using ffprobe"""
        if not os.path.exists(path):
            frappe.throw(_("Video file not found: {0}").format(path))
        
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "json",
                path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            
            if result.returncode != 0:
                frappe.throw(_("Failed to read video dimensions: {0}").format(result.stderr))
            
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            
            if not streams:
                frappe.throw(_("No video stream found in file"))
            
            stream = streams[0]
            width = stream.get("width")
            height = stream.get("height")
            
            if not width or not height:
                frappe.throw(_("Could not determine video dimensions"))
            
            return int(width), int(height)
        
        except Exception as e:
            frappe.throw(_("Error reading video dimensions: {0}").format(str(e)))
    
    def validate_facebook_content(self):
        """Facebook-specific validations"""
        selected_types = sum([self.is_fb_post or 0, self.is_fb_reel or 0, self.is_fb_story or 0])
        if selected_types > 1:
            frappe.throw(
                _("Please select only one Facebook content type: Post, Reel, or Story"),
                title=_("Multiple Content Types Selected"),
            )
            
        # Post validation
        if self.is_fb_post:
            pass
        
        # Reel Validation 
        if self.is_fb_reel:
            if not self.media or len(self.media) != 1:
                frappe.throw(_("Facebook Reels require one video file"))
                # Check if media is a video
            media_item = self.media[0]
            
            file_type = (media_item.file_type or "").lower()
            if "video" not in file_type:
                frappe.throw(_("Facebook Reels require video files (.mp4 or .mov)"))
            
            full_path = self._get_full_path(media_item.file)
            if media_item.file_size > 1024 * 1024 * 1024:
                frappe.throw(_("Facebook Reels must be under 1GB"))
                
            duration = self._get_video_duration(full_path)
            media_item.duration = duration
            
            if duration < 3 or duration > 90:
                frappe.throw(_("Facebook Reels must be between 3 and 90 seconds (got {0:.1f}s)").format(duration))
            
            width, height = self._get_video_dimensions(full_path)
            if height <= width:
                frappe.throw(
                    _("Facebook Reels must be vertical (portrait). Got {0}x{1}").format(width, height)
                )
                
            ratio = height / width
            if ratio < 1.3:
                frappe.throw(
                    _("Facebook Reels should be 9:16 aspect ratio. Got {0:.2f}:1").format(ratio)
                )
        
        if self.is_fb_story:
            if not self.media or len(self.media) == 0:
                frappe.throw(_("Facebook Stories require at least one media file"))
            
            if len(self.media) > 1:
                frappe.throw(_("Facebook Stories support only one media file at a time"))
            
            media_item = self.media[0]
            file_type = (media_item.file_type or "").lower()
            full_path = self._get_full_path(media_item.file)

            if "video" in file_type:
                # Check file size (100MB limit for story videos)
                if media_item.file_size > 100 * 1024 * 1024:
                    frappe.throw(_("Facebook Story videos must be under 100MB"))
                
                duration = self._get_video_duration(full_path)
                media_item.duration = duration
                
                if duration > 60:
                    frappe.throw(_("Facebook Story videos must be 60 seconds or less (got {0:.1f}s)").format(duration))

                # width, height = self._get_video_dimensions(full_path)
                
                # if height <= width:
                #     frappe.throw(
                #         _("Facebook Story videos must be vertical. Got {0}x{1}").format(width, height)
                #     )

            elif "image" in file_type:
                # ✅ Check file size (8MB limit for story images)
                if media_item.file_size > 8 * 1024 * 1024:
                    frappe.throw(_("Facebook Story images must be under 8MB"))
                
                # try:
                #     with image.open(full_path) as img:
                #         # if img.height <= img.width:
                #         #     frappe.throw(
                #         #         _("Facebook Story images must be vertical. Got {0}x{1}").format(img.width, img.height)
                #         #     )
                # except Exception as e:
                #     frappe.throw(_("Failed to read image file: {0}").format(str(e)))
            else:
                frappe.throw(_("Facebook Stories require either an image or video file"))

    def validate_instagram_content(self):
        """Instagram-specific validations"""
        # Ensure only one content type is selected
        selected_types = sum([self.is_ig_post or 0, self.is_ig_reel or 0, self.is_ig_story or 0])

        if selected_types > 1:
            frappe.throw(
                _("Please select only one Instagram content type: Post, Reel, or Story"),
                title=_("Multiple Content Types Selected"),
            )

        # Story-specific validations
        if self.is_ig_story:
            if not self.media or len(self.media) == 0:
                frappe.throw(_("Instagram Stories require at least one media file"))

        # Reel-specific validations
        if self.is_ig_reel:
            if not self.media or len(self.media) != 1:
                frappe.throw(_("Instagram Reels require exactly one video file"))

            # Check if media is a video
            media_item = self.media[0]
            file_type = (media_item.file_type or "").lower()
            
            if "video" not in file_type:
                frappe.throw(_("Instagram Reels require video files (.mp4 or .mov)"))

            full_path = self._get_full_path(media_item.file)
            duration = self._get_video_duration(full_path)
            media_item.duration = duration  # ✅ SAVE IT
        
        # Add duration validation if needed
            if duration < 3 or duration > 90:
                frappe.throw(_("Instagram Reels must be between 3 and 90 seconds (got {0:.1f}s)").format(duration))

        # Post-specific validations
        if self.is_ig_post:
            if not self.media or len(self.media) == 0:
                frappe.throw(_("Instagram Posts require at least one media file"))


    def validate_youtube_content(self):
        """YouTube-specific validations"""
        if not self.media or len(self.media) != 1:
            frappe.throw(_("YouTube posts require exactly one video file"))

        # Check if media is a video
        media_item = self.media[0]
        file_type = (media_item.file_type or "").lower()
        if "video" not in file_type:
            frappe.throw(_("YouTube requires video files"))

        if not self.video_title:
            frappe.throw(_("YouTube videos require a title"))


    def validate_content_length(self):
        """Validate content length against platform limits"""
        from frappe_social.frappe_social.providers import get_provider

        if not self.platform:
            return

        content_length = len(self.content or "")
        try:
            provider_class = get_provider(self.platform)
            max_length = provider_class.MAX_CONTENT_LENGTH
            if content_length > max_length:
                frappe.throw(
                    _(f"Content exceeds {self.platform} limit of {max_length} characters"),
                    title=_("Content Too Long"),
                )
        except Exception as e:
            frappe.log_error("Social provider loading error", str(e))

    def validate_media(self):
        """Validate media files against platform requirements"""
        from frappe_social.frappe_social.providers import get_provider

        if not self.platform or not self.media:
            return

        provider_class = get_provider(self.platform)
        num_media = len(self.media)
        num_videos = 0

        if num_media > provider_class.MAX_MEDIA_COUNT:
            frappe.throw(
                f"Too many media files for {self.platform}: {num_media} > {provider_class.MAX_MEDIA_COUNT}"
            )

        for media in self.media:
            file_type = (media.file_type or "").lower()
            file_size = media.file_size or 0

            is_image = "image" in file_type
            is_video = "video" in file_type

            if not (is_image or is_video):
                frappe.throw(f"Unsupported media type '{file_type}' for {self.platform} (File: {media.file})")

            allowed_types = (
                provider_class.ALLOWED_IMAGE_TYPES if is_image else provider_class.ALLOWED_VIDEO_TYPES
            )

            # Auto-correct jpg to jpeg
            if is_image and "image/jpeg" in allowed_types and file_type == "image/jpg":
                media.file_type = "image/jpeg"
            elif file_type not in allowed_types:
                frappe.throw(
                    f"Media type '{file_type}' is not allowed on {self.platform}. "
                    f"Allowed: {', '.join(allowed_types)}"
                )

            max_size = provider_class.MAX_IMAGE_SIZE if is_image else provider_class.MAX_VIDEO_SIZE

            if file_size > max_size:
                size_mb = file_size / (1024 * 1024)
                max_mb = max_size / (1024 * 1024)
                frappe.throw(f"File too large: {size_mb:.2f}MB > {max_mb:.2f}MB")

            if is_video:
                num_videos += 1

        if num_videos > 1 and not provider_class.ALLOWS_MULTI_VIDEO:
            frappe.throw(f"{self.platform} does not support multiple videos")

    def can_transition_to(self, new_status: str) -> bool:
        """Check if status transition is valid"""
        return new_status in self.VALID_TRANSITIONS.get(self.status, [])

    def set_status(self, new_status: str):
        """Set status with validation"""
        if self.can_transition_to(new_status):
            self.status = new_status
            self.save(ignore_permissions=True)
        else:
            frappe.throw(f"Cannot change status from {self.status} to {new_status}")

    def validate_update_after_submit(self):
        """Allow status updates after submission"""
        if self.get_doc_before_save():
            old_status = self.get_doc_before_save().status
            if self.status != old_status:
                return

        super().validate_update_after_submit()


@frappe.whitelist()
def get_platforms_for_organization(organization):
    """Get available platforms for an organization"""
    if not organization:
        return []

    return frappe.db.get_all(
        "Social Integration",
        filters={"organization": organization, "enabled": 1, "connection_status": "Connected"},
        pluck="platform",
        distinct=True,
        order_by="platform asc",
    )