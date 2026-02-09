# social_post.py - Updated validation section

import frappe
from frappe.model.document import Document
from frappe import _
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
                self.is_ig_post = 1  # Default to regular post

        # For Facebook, ensure at least one content type is selected
        elif self.platform == "Facebook":
            if not (self.is_fb_post or self.is_fb_reel or self.is_fb_story):
                self.is_fb_post = 1  # Default to regular post

    def validate(self):
        """Validate the post before saving/submitting"""
        # 1. Fix media metadata first
        self.fix_media_metadata()

        # 2. Platform-specific validations
        if self.platform == "Instagram":
            self.validate_instagram_content()
        elif self.platform == "Facebook":
            self.validate_facebook_content()
        elif self.platform == "YouTube":
            self.validate_youtube_content()

        # 3. General validations
        self.validate_content_length()
        self.validate_media()

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

            if len(self.media) > 1:
                frappe.throw(_("Instagram Stories support only one media file at a time"))

        # Reel-specific validations
        if self.is_ig_reel:
            if not self.media or len(self.media) == 0:
                frappe.throw(_("Instagram Reels require a video file"))

            if len(self.media) > 1:
                frappe.throw(_("Instagram Reels support only one video at a time"))

            # Check if media is a video
            media_item = self.media[0]
            file_type = (media_item.file_type or "").lower()
            if "video" not in file_type:
                frappe.throw(_("Instagram Reels require video files (.mp4 or .mov)"))

        # Post-specific validations
        if self.is_ig_post:
            if not self.media or len(self.media) == 0:
                frappe.throw(_("Instagram Posts require at least one media file"))

            # Carousel (multiple images) validation
            if len(self.media) > 1:
                for media_item in self.media:
                    file_type = (media_item.file_type or "").lower()
                    if "image" not in file_type:
                        frappe.throw(
                            _(
                                "Instagram carousels (multiple media) currently support only images. "
                                "Please use single media for videos."
                            )
                        )

    def validate_facebook_content(self):
        """Facebook-specific validations"""
        # CTA validation (only for Feed posts)
        if self.cta:
            if not self.is_fb_post:
                frappe.throw(
                    _("Call-to-Action (CTA) is only available for Facebook Feed posts"),
                    title=_("Invalid CTA Usage"),
                )

            if not self.link:
                frappe.throw(
                    _("Please provide a link for the Call-to-Action button"), title=_("Missing CTA Link")
                )

        # Story validations
        if self.is_fb_story:
            if not self.media or len(self.media) == 0:
                frappe.throw(_("Facebook Stories require at least one media file"))

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