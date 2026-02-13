# social_post.py - Updated validation section

import frappe
from frappe import _
import subprocess, json
import os
from frappe.model.document import Document
from frappe_social.frappe_social.providers import get_provider
from frappe_social.frappe_social.utils.media import (
    get_full_path,
    get_video_duration,
    get_video_dimensions,
    is_video,
    is_image,
    normalize_file_type,
)

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

        if self.platform == "Instagram":
            if not (self.is_ig_post or self.is_ig_reel or self.is_ig_story):
                frappe.throw(
                _("Please select any one Instagram content type: Post, Reel, or Story"),
                title=_("Content Type"),
            )

        elif self.platform == "Facebook":
            if not (self.is_fb_post or self.is_fb_reel or self.is_fb_story):
                frappe.throw(
                    _("Please select any one Facebook content type: Post, Reel, or Story"),
                    title=_("Content Type"),
                )
        elif self.platform == "YouTube":
            if not (self.is_yt_post or self.is_short or self.is_video):
                frappe.throw(
                    _("Please select any one YouTube content type: Post, Short, or Video"),
                    title=_("Content Type"),
                )

    def validate(self):
        """Validate the post before saving/submitting"""
        
        self.fix_media_metadata()
    
        switch = {
            "Facebook": self.validate_facebook_content,
            "Instagram": self.validate_instagram_content,
            "YouTube": self.validate_youtube_content,
            "LinkedIn": lambda: None,
            "Twitter": lambda: None,
        }
        
        if self.platform in switch:
            switch[self.platform]()
        else:
            frappe.throw(_("Unsupported platform: {0}").format(self.platform))

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
    
    def validate_facebook_content(self):
        """Facebook-specific validations"""            
        # Post validation
        if self.is_fb_post:           
            for media_item in self.media:
                file_type = (media_item.file_type or "").lower()
                full_path = get_full_path(media_item.file)

                if "video" in file_type:
                    if media_item.file_size > get_provider("Facebook").MAX_VIDEO_SIZE: # 4GB
                        size_mb = media_item.file_size / (1024 * 1024)
                        max_mb = get_provider("Facebook").MAX_VIDEO_SIZE / (1024 * 1024)
                        frappe.throw(_("Facebook Post videos must be under {0:.2f} MB (got {1:.2f} MB)").format(max_mb, size_mb))
                    
                    duration = get_video_duration(full_path)
                    media_item.duration = duration
                    
                    if duration > get_provider("Facebook").MAX_VIDEO_DURATION:
                        duration = media_item.duration
                        frappe.throw(_("Facebook Post videos must be less than or equal to {0} seconds (got {1:.1f}s)").format(get_provider("Facebook").MAX_VIDEO_DURATION, duration))
                else:
                    if media_item.file_size > get_provider("Facebook").MAX_IMAGE_SIZE: # 30MB
                        size_mb = media_item.file_size / (1024 * 1024)
                        max_mb = get_provider("Facebook").MAX_IMAGE_SIZE / (1024 * 1024)
                        frappe.throw(_("Facebook Post images must be under {0:.2f} MB (got {1:.2f} MB)").format(max_mb, size_mb))
        
        # Reel Validation 
        if self.is_fb_reel:
            if not self.media or len(self.media) != 1:
                frappe.throw(_("Facebook Reels require one video file"))

            media_item = self.media[0]
            file_type = (media_item.file_type or "").lower()
            
            if "video" not in file_type:
                frappe.throw(_("Facebook Reels require video files (.mp4 or .mov)"))
            
            full_path = get_full_path(media_item.file)
            if media_item.file_size > get_provider("Facebook").REEL_MAX_VIDEO_SIZE: # 1GB
                size_mb = media_item.file_size / (1024 * 1024)
                max_mb = get_provider("Facebook").REEL_MAX_VIDEO_SIZE / (1024 * 1024)
                frappe.throw(_("Facebook Reels must be under {0:.2f} MB (got {1:.2f} MB)").format(max_mb, size_mb))
                
            duration = get_video_duration(full_path)
            media_item.duration = duration
            
            if duration < get_provider("Facebook").REEL_MIN_DURATION or duration > get_provider("Facebook").REEL_MAX_DURATION:
                duration = media_item.duration
                frappe.throw(_("Facebook Reels must be between 3 and 90 seconds (got {0:.1f}s)").format(duration))
            
            # width, height = get_video_dimensions(full_path)
            # if height <= width:
            #     frappe.throw(
            #         _("Facebook Reels must be vertical (portrait). Got {0}x{1}").format(width, height)
            #     )
                
            # ratio = height / width
            # if ratio < 1.3:
            #     frappe.throw(
            #         _("Facebook Reels should be 9:16 aspect ratio. Got {0:.2f}:1").format(ratio)
            #     )
        
        if self.is_fb_story:
            if not self.media or len(self.media) == 0:
                frappe.throw(_("Facebook Stories require at least one media file"))
            
            if len(self.media) > 1:
                frappe.throw(_("Facebook Stories support only one media file at a time"))
            
            media_item = self.media[0]
            file_type = (media_item.file_type or "").lower()
            full_path = get_full_path(media_item.file)

            if "video" in file_type:
                if media_item.file_size > get_provider("Facebook").STORY_MAX_VIDEO_SIZE: # 100MB
                    size_mb = media_item.file_size / (1024 * 1024)
                    max_mb = get_provider("Facebook").STORY_MAX_VIDEO_SIZE / (1024 * 1024)
                    frappe.throw(_("Facebook Story videos must be under {0:.2f} MB (got {1:.2f} MB)").format(max_mb, size_mb))
                
                duration = get_video_duration(full_path)
                media_item.duration = duration
                
                if duration > get_provider("Facebook").STORY_MAX_VIDEO_DURATION:
                    duration = media_item.duration
                    frappe.throw(_("Facebook Story videos must be between 1- 120 seconds (got {0:.1f}s)").format(duration))

                # width, height = self._get_video_dimensions(full_path)
                
                # if height <= width:
                #     frappe.throw(
                #         _("Facebook Story videos must be vertical. Got {0}x{1}").format(width, height)
                #     )

            else:
                if media_item.file_size > get_provider("Facebook").STORY_MAX_IMAGE_SIZE: # 8MB
                    size_mb = media_item.file_size / (1024 * 1024)
                    max_mb = get_provider("Facebook").STORY_MAX_IMAGE_SIZE / (1024 * 1024)
                    frappe.throw(_("Facebook Story images must be under {0:.2f} MB (got {1:.2f} MB)").format(max_mb, size_mb))
                
                # try:
                #     with image.open(full_path) as img:
                #         # if img.height <= img.width:
                #         #     frappe.throw(
                #         #         _("Facebook Story images must be vertical. Got {0}x{1}").format(img.width, img.height)
                #         #     )
                # except Exception as e:
                #     frappe.throw(_("Failed to read image file: {0}").format(str(e)))

    def validate_instagram_content(self):
        """Instagram-specific validations"""
        
        # Post-specific validations
        if self.is_ig_post:
            if not self.media or len(self.media) == 0:
                frappe.throw(_("Instagram Posts require at least one media file"))
                
            media_item = self.media[0]
            file_type = (media_item.file_type or "").lower()
            
            if "video" in file_type:
                frappe.throw(_("Instagram Posts do not support videos"))
                # if media_item.file_size > get_provider("Instagram").MAX_VIDEO_SIZE:
                #     size_mb = media_item.file_size / (1024 * 1024)
                #     max_mb = get_provider("Instagram").MAX_VIDEO_SIZE / (1024 * 1024)
                #     frappe.throw(_("Instagram Post videos must be under {0:.2f} MB (got {1:.2f} MB)").format(max_mb, size_mb))
                # if media_item.duration > get_provider("Instagram").MAX_VIDEO_DURATION:
                #     duration = media_item.duration
                #     frappe.throw(_("Instagram Post videos must be under {0} seconds (got {1:.1f}s)").format(get_provider("Instagram").MAX_VIDEO_DURATION, duration))
            elif "image" in file_type:
                if len(self.media) > get_provider("Instagram").MAX_IMAGES:
                    frappe.throw(_("Instagram Posts support a maximum of {0} images").format(get_provider("Instagram").MAX_IMAGES))
                if media_item.file_size > get_provider("Instagram").MAX_IMAGE_SIZE:
                    size_mb = media_item.file_size / (1024 * 1024)
                    max_mb = get_provider("Instagram").MAX_IMAGE_SIZE / (1024 * 1024)
                    frappe.throw(_("Instagram Post images must be under {0:.2f} MB (got {1:.2f} MB)").format(max_mb, size_mb))
            else:
                frappe.throw(_("Instagram Posts only support image files"))
                
         # Reel-specific validations
        if self.is_ig_reel:
            if not self.media or len(self.media) != 1:
                frappe.throw(_("Instagram Reels require exactly one video file"))

            media_item = self.media[0]
            file_type = (media_item.file_type or "").lower()
            
            if "video" not in file_type:
                frappe.throw(_("Instagram Reels require video files"))

            if media_item.file_size > get_provider("Instagram").REEL_MAX_VIDEO_SIZE:
                size_mb = media_item.file_size / (1024 * 1024)
                max_mb = get_provider("Instagram").REEL_MAX_VIDEO_SIZE / (1024 * 1024)
                frappe.throw(_("Instagram Reels must be under {0:.2f} MB (got {1:.2f} MB)").format(max_mb, size_mb))

            full_path = get_full_path(media_item.file)
            duration = get_video_duration(full_path)
            media_item.duration = duration  
            
            if duration < get_provider("Instagram").REEL_MIN_DURATION or duration > get_provider("Instagram").REEL_MAX_DURATION:
                frappe.throw(_("Instagram Reels must be between 3 and 90 seconds (got {0:.1f}s)").format(duration))
                
        # Story-specific validations
        if self.is_ig_story:
            if not self.media or len(self.media) == 0:
                frappe.throw(_("Instagram Stories require at least one media file"))
            
            if len(self.media) > 10:
                frappe.throw(_("Instagram Stories support a maximum of 10 media files"))
                
            media_item = self.media[0]
            file_type = (media_item.file_type or "").lower()
            full_path = get_full_path(media_item.file)

            if "video" in file_type:
                # Check file size (100MB limit for story videos)
                if media_item.file_size > get_provider("Instagram").STORY_MAX_VIDEO_SIZE:
                    size_mb = media_item.file_size / (1024 * 1024)
                    max_mb = get_provider("Instagram").STORY_MAX_VIDEO_SIZE / (1024 * 1024)
                    frappe.throw(_("Instagram Story videos must be under {0:.2f} MB (got {1:.2f} MB)").format(max_mb, size_mb))
                    
                duration = get_video_duration(full_path)
                media_item.duration = duration
                
                if duration > get_provider("Instagram").MAX_STORY_VIDEO_DURATION:
                    frappe.throw(_("Instagram Story videos must be less than or equal to {0} seconds (got {1:.1f}s)").format(get_provider("Instagram").MAX_STORY_VIDEO_DURATION, duration))
            else:
                # Check file size (8MB limit for story images)
                if media_item.file_size > get_provider("Instagram").STORY_MAX_IMAGE_SIZE:
                    size_mb = media_item.file_size / (1024 * 1024)
                    max_mb = get_provider("Instagram").STORY_MAX_IMAGE_SIZE / (1024 * 1024)
                    frappe.throw(_("Instagram Story images must be under {0:.2f} MB (got {1:.2f} MB)").format(max_mb, size_mb))

    def validate_youtube_content(self):
        """YouTube-specific validations"""
        
        if self.is_yt_post:
            # Community posts can have text only or text with images
            if not self.media or len(self.media) == 0:
                # Text-only post is allowed
                if not self.content:
                    frappe.throw(_("YouTube Community Posts require either content or media"))
                return
            
            # Validate media count (1-10 images allowed)
            if len(self.media) > 10:
                frappe.throw(_("YouTube Community Posts support a maximum of 10 images (got {0})").format(len(self.media)))
            
            # Validate each media item is an image
            for idx, media_item in enumerate(self.media, 1):
                file_type = (media_item.file_type or "").lower()
                
                if "video" in file_type:
                    frappe.throw(_("YouTube Community Posts do not support videos. Please use images only."))
                
                if "image" not in file_type:
                    frappe.throw(_("YouTube Community Posts only support images (got {0} for file {1})").format(file_type, idx))
                
                # Validate file type
                allowed_image_types = get_provider("YouTube").ALLOWED_IMAGE_TYPES
                if file_type not in allowed_image_types:
                    frappe.throw(_("Image type '{0}' not allowed. Allowed types: {1}").format(
                        file_type, ", ".join(allowed_image_types)
                    ))
                
                # Validate file size (8MB limit for community post images)
                if media_item.file_size > get_provider("YouTube").MAX_IMAGE_SIZE:
                    size_mb = media_item.file_size / (1024 * 1024)
                    max_mb = get_provider("YouTube").MAX_IMAGE_SIZE / (1024 * 1024)
                    frappe.throw(_("YouTube Community Post images must be under {0:.2f} MB (image {1} is {2:.2f} MB)").format(
                        max_mb, idx, size_mb
                    ))
            
            # Content is optional for posts with images
            return
        
        if self.is_short:
            # Shorts require exactly one video file
            if not self.media or len(self.media) != 1:
                frappe.throw(_("YouTube Shorts require exactly one video file"))
            
            media_item = self.media[0]
            file_type = (media_item.file_type or "").lower()
            
            # Must be a video
            if "video" not in file_type:
                frappe.throw(_("YouTube Shorts require a video file (.mp4 or .mov)"))
            
            # Validate file type
            allowed_video_types = get_provider("YouTube").ALLOWED_VIDEO_TYPES
            if file_type not in allowed_video_types:
                frappe.throw(_("Video type '{0}' not allowed. Allowed types: {1}").format(
                    file_type, ", ".join(allowed_video_types)
                ))
            
            # Get file path for detailed validation
            full_path = get_full_path(media_item.file)
            
            # Validate file size (256GB max, but typically much smaller for Shorts)
            if media_item.file_size > get_provider("YouTube").MAX_VIDEO_SIZE:
                size_mb = media_item.file_size / (1024 * 1024)
                max_mb = get_provider("YouTube").MAX_VIDEO_SIZE / (1024 * 1024)
                frappe.throw(_("YouTube Shorts must be under {0:.2f} MB (got {1:.2f} MB)").format(
                    max_mb, size_mb
                ))
            
            # Validate duration (must be 60 seconds or less)
            duration = get_video_duration(full_path)
            media_item.duration = duration
            
            if duration > 60:
                frappe.throw(_("YouTube Shorts must be 60 seconds or less (got {0:.1f} seconds)").format(duration))
            
            if duration < 1:
                frappe.throw(_("YouTube Shorts must be at least 1 second long"))
            
            # Validate aspect ratio (must be vertical 9:16 or square 1:1)
            width, height = get_video_dimensions(full_path)
            
            if height < width:
                frappe.throw(_("YouTube Shorts must be vertical (9:16) or square (1:1). Got {0}x{1} (horizontal)").format(
                    width, height
                ))
            
            # Check minimum resolution (720p height minimum)
            if height < 720:
                frappe.throw(_("YouTube Shorts require minimum 720p vertical resolution. Got {0}x{1}").format(
                    width, height
                ))
            
            # Calculate and validate aspect ratio
            aspect_ratio = height / width if width > 0 else 0
            
            # Allow 9:16 (1.778) or 1:1 (1.0) with some tolerance
            is_vertical = aspect_ratio >= 1.5  # 9:16 is ~1.778
            is_square = 0.95 <= aspect_ratio <= 1.05  # 1:1 with 5% tolerance
            
            if not (is_vertical or is_square):
                frappe.throw(_("YouTube Shorts must be vertical (9:16 aspect ratio) or square (1:1). Got {0:.2f}:1").format(
                    aspect_ratio
                ))
            
            # Title is required
            if not self.video_title:
                frappe.throw(_("YouTube Shorts require a title"))
            
            # Validate title length (100 characters max)
            if len(self.video_title) > 100:
                frappe.throw(_("YouTube video title must be 100 characters or less (got {0})").format(
                    len(self.video_title)
                ))
            
            # Description is optional but validate if provided
            if self.content and len(self.content) > 5000:
                frappe.throw(_("YouTube description must be 5000 characters or less (got {0})").format(
                    len(self.content)
                ))
            
            # Note: #Shorts tag will be automatically added by the provider
            return
        
        if self.is_video:
            # Regular videos require exactly one video file
            if not self.media or len(self.media) != 1:
                frappe.throw(_("YouTube Videos require exactly one video file"))
            
            media_item = self.media[0]
            file_type = (media_item.file_type or "").lower()
            
            # Must be a video
            if "video" not in file_type:
                frappe.throw(_("YouTube Videos require a video file (.mp4 or .mov)"))
            
            # Validate file type
            allowed_video_types = get_provider("YouTube").ALLOWED_VIDEO_TYPES
            if file_type not in allowed_video_types:
                frappe.throw(_("Video type '{0}' not allowed. Allowed types: {1}").format(
                    file_type, ", ".join(allowed_video_types)
                ))
            
            # Get file path for detailed validation
            full_path = get_full_path(media_item.file)
            
            # Validate file size (256GB max for YouTube)
            if media_item.file_size > get_provider("YouTube").MAX_VIDEO_SIZE:
                size_gb = media_item.file_size / (1024 * 1024 * 1024)
                max_gb = get_provider("YouTube").MAX_VIDEO_SIZE / (1024 * 1024 * 1024)
                frappe.throw(_("YouTube Videos must be under {0:.2f} GB (got {1:.2f} GB)").format(
                    max_gb, size_gb
                ))
            
            # Validate duration (max 12 hours for non-verified, 15 minutes for unverified)
            duration = get_video_duration(full_path)
            media_item.duration = duration
            
            max_duration = get_provider("YouTube").MAX_VIDEO_DURATION  # 12 hours in seconds
            if duration > max_duration:
                max_hours = max_duration / 3600
                got_hours = duration / 3600
                frappe.throw(_("YouTube Videos must be under {0:.1f} hours (got {1:.2f} hours)").format(
                    max_hours, got_hours
                ))
            
            if duration < 1:
                frappe.throw(_("YouTube Videos must be at least 1 second long"))
            
            # Get video dimensions for validation
            width, height = get_video_dimensions(full_path)
            
            # Check minimum resolution (426x240 minimum)
            if width < 426 or height < 240:
                frappe.throw(_("YouTube Videos require minimum 426x240 resolution. Got {0}x{1}").format(
                    width, height
                ))
            
            # Title is required
            if not self.video_title:
                frappe.throw(_("YouTube Videos require a title"))
            
            # Validate title length (100 characters max)
            if len(self.video_title) > 100:
                frappe.throw(_("YouTube video title must be 100 characters or less (got {0})").format(
                    len(self.video_title)
                ))
            
            # Description is optional but validate if provided
            if self.content and len(self.content) > 5000:
                frappe.throw(_("YouTube description must be 5000 characters or less (got {0})").format(
                    len(self.content)
                ))
            
            # Validate thumbnail if provided (optional but recommended)
            if self.thumbnail:
                # Thumbnail validation will be handled by the provider
                # Just check if file exists
                thumbnail_path = frappe.get_site_path("public", self.thumbnail.lstrip("/"))
                if not os.path.exists(thumbnail_path):
                    frappe.throw(_("Thumbnail file not found: {0}").format(self.thumbnail))
                
                # Check thumbnail size (2MB max for YouTube)
                thumbnail_size = os.path.getsize(thumbnail_path)
                max_thumbnail_size = 2 * 1024 * 1024  # 2MB
                if thumbnail_size > max_thumbnail_size:
                    size_mb = thumbnail_size / (1024 * 1024)
                    frappe.throw(_("YouTube thumbnail must be under 2 MB (got {0:.2f} MB)").format(size_mb))
            
            return    

    def validate_content_length(self):
        """Validate content length against platform limits"""
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

        if not self.platform or not self.media:
            return

        provider_class = get_provider(self.platform)
        num_media = len(self.media)
        num_videos = 0

        if num_media > provider_class.MAX_IMAGES:
            frappe.throw(
                f"Too many media files for {self.platform}: {num_media} > {provider_class.MAX_IMAGES}"
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