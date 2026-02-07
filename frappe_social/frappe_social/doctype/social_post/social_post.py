import frappe
from frappe.model.document import Document
from frappe import _
from frappe_social.frappe_social.utils.media import normalize_file_type
import os
import json
import re
import html
from typing import Dict, List, Optional


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
        # Skip defaults for ads
        if self.is_ad:
            return

        # For Instagram, ensure at least one content type is selected
        if self.platform == "Instagram":
            if not (self.is_post or self.is_reel or self.is_story):
                self.is_post = 1  # Default to regular post

        # For Facebook, ensure at least one content type is selected
        elif self.platform == "Facebook":
            if not (self.is_post or self.is_reel or self.is_story):
                self.is_post = 1  # Default to regular post

    def validate(self):
        """Validate the post before saving/submitting"""
        # 1. Fix media metadata first
        self.fix_media_metadata()

        # 2. Validate based on mode (ad or normal post)
        if self.is_ad:
            self.validate_ad_mode()
        else:
            self.validate_normal_post_mode()

    def validate_ad_mode(self):
        """Validate ad-specific requirements"""
        # Validate all ad fields
        self.validate_ad_fields()

        # Ads still need media and content validation
        if self.media:
            self.validate_media()
        if self.content:
            self.validate_content_length()

    def validate_normal_post_mode(self):
        """Validate normal post requirements"""
        # Require account for normal posts
        if not self.account:
            frappe.throw(
                _("Account is required for publishing posts"),
                title=_("Missing Account")
            )

        # Platform-specific validations
        if self.platform == "Instagram":
            self.validate_instagram_content()
        elif self.platform == "Facebook":
            self.validate_facebook_content()
        elif self.platform == "YouTube":
            self.validate_youtube_content()

        # General validations
        self.validate_content_length()
        self.validate_media()

    def validate_ad_fields(self):
        """Validate all required fields for ad creation"""
        required_fields = {
            'campagin': 'Campaign',
            'select_ad_account': 'Ads Account Integration',
            'select_ad_set': 'Ad Set',
            'selected_facebook_page': 'Facebook Pages'
        }

        for field, label in required_fields.items():
            if not self.get(field):
                frappe.throw(
                    _(f"{label} is required for ad creation"),
                    title=_("Missing Required Field")
                )

        # Verify campaign is Meta Ads
        try:
            campaign = frappe.get_doc('Marketing Campaign', self.campagin)
            if not campaign.get('custom_is_meta_ads'):
                frappe.throw(
                    _("Selected campaign is not a Meta Ads campaign"),
                    title=_("Invalid Campaign")
                )
        except frappe.DoesNotExistError:
            frappe.throw(
                _("Campaign not found"),
                title=_("Invalid Campaign")
            )

        # Verify ad account is connected
        try:
            ad_account = frappe.get_doc('Ads Account Integration', self.select_ad_account)
            if ad_account.connection_status != 'Connected':
                frappe.throw(
                    _("Selected ad account is not connected. Please reconnect it."),
                    title=_("Account Not Connected")
                )
        except frappe.DoesNotExistError:
            frappe.throw(
                _("Ad Account not found"),
                title=_("Invalid Ad Account")
            )

        # Verify ad set belongs to campaign
        try:
            ad_set = frappe.get_doc('Ad Set', self.select_ad_set)
            if ad_set.campaign != self.campagin:
                frappe.throw(
                    _("Selected ad set does not belong to the selected campaign"),
                    title=_("Invalid Ad Set")
                )

            # Verify ad set has been created on Meta
            if not ad_set.adset_id:
                frappe.throw(
                    _("Selected ad set has not been created on Meta yet. Please save the ad set first."),
                    title=_("Ad Set Not Created")
                )
        except frappe.DoesNotExistError:
            frappe.throw(
                _("Ad Set not found"),
                title=_("Invalid Ad Set")
            )

    def validate_instagram_content(self):
        """Instagram-specific validations"""
        # Ensure only one content type is selected
        selected_types = sum([
            1 if self.is_post else 0,
            1 if self.is_reel else 0,
            1 if self.is_story else 0
        ])

        if selected_types > 1:
            frappe.throw(
                _("Please select only one Instagram content type: Post, Reel, or Story"),
                title=_("Multiple Content Types Selected"),
            )

        if selected_types == 0:
            frappe.throw(
                _("Please select at least one Instagram content type: Post, Reel, or Story"),
                title=_("No Content Type Selected"),
            )

        # Story-specific validations
        if self.is_story:
            if not self.media or len(self.media) == 0:
                frappe.throw(
                    _("Instagram Stories require at least one media file"),
                    title=_("Media Required")
                )

            if len(self.media) > 1:
                frappe.throw(
                    _("Instagram Stories support only one media file at a time"),
                    title=_("Too Many Media Files")
                )

        # Reel-specific validations
        if self.is_reel:
            if not self.media or len(self.media) == 0:
                frappe.throw(
                    _("Instagram Reels require a video file"),
                    title=_("Media Required")
                )

            if len(self.media) > 1:
                frappe.throw(
                    _("Instagram Reels support only one video at a time"),
                    title=_("Too Many Videos")
                )

            # Check if media is a video
            media_item = self.media[0]
            file_type = (media_item.file_type or "").lower()
            if "video" not in file_type:
                frappe.throw(
                    _("Instagram Reels require video files (.mp4 or .mov)"),
                    title=_("Invalid Media Type")
                )

        # Post-specific validations
        if self.is_post:
            if not self.media or len(self.media) == 0:
                frappe.throw(
                    _("Instagram Posts require at least one media file"),
                    title=_("Media Required")
                )

            # Carousel (multiple images) validation
            if len(self.media) > 1:
                for media_item in self.media:
                    file_type = (media_item.file_type or "").lower()
                    if "image" not in file_type:
                        frappe.throw(
                            _(
                                "Instagram carousels (multiple media) currently support only images. "
                                "Please use single media for videos."
                            ),
                            title=_("Invalid Carousel Media")
                        )

            # Instagram allows max 10 images in carousel
            if len(self.media) > 10:
                frappe.throw(
                    _("Instagram allows maximum 10 images in a carousel"),
                    title=_("Too Many Media Files")
                )

    def validate_facebook_content(self):
        """Facebook-specific validations"""
        # Ensure only one content type is selected
        selected_types = sum([
            1 if self.is_post else 0,
            1 if self.is_reel else 0,
            1 if self.is_story else 0
        ])

        if selected_types > 1:
            frappe.throw(
                _("Please select only one Facebook content type: Post, Reel, or Story"),
                title=_("Multiple Content Types Selected"),
            )

        if selected_types == 0:
            frappe.throw(
                _("Please select at least one Facebook content type"),
                title=_("No Content Type Selected"),
            )

        # Story validations
        if self.is_story:
            if not self.media or len(self.media) == 0:
                frappe.throw(
                    _("Facebook Stories require at least one media file"),
                    title=_("Media Required")
                )

            if len(self.media) > 1:
                frappe.throw(
                    _("Facebook Stories support only one media file at a time"),
                    title=_("Too Many Media Files")
                )

        # Reel validations
        if self.is_reel:
            if not self.media or len(self.media) == 0:
                frappe.throw(
                    _("Facebook Reels require a video file"),
                    title=_("Media Required")
                )

            if len(self.media) > 1:
                frappe.throw(
                    _("Facebook Reels support only one video at a time"),
                    title=_("Too Many Videos")
                )

            # Check if media is a video
            media_item = self.media[0]
            file_type = (media_item.file_type or "").lower()
            if "video" not in file_type:
                frappe.throw(
                    _("Facebook Reels require video files"),
                    title=_("Invalid Media Type")
                )

    def validate_youtube_content(self):
        """YouTube-specific validations"""
        if not self.media or len(self.media) != 1:
            frappe.throw(
                _("YouTube posts require exactly one video file"),
                title=_("Invalid Media Count")
            )

        # Check if media is a video
        media_item = self.media[0]
        file_type = (media_item.file_type or "").lower()
        if "video" not in file_type:
            frappe.throw(
                _("YouTube requires video files"),
                title=_("Invalid Media Type")
            )

        if not self.video_title:
            frappe.throw(
                _("YouTube videos require a title"),
                title=_("Missing Video Title")
            )

    def fix_media_metadata(self):
        """Fix media metadata (file type and size)"""
        if not self.media:
            return

        for item in self.media:
            if not item.file:
                continue

            try:
                db_file = frappe.db.get_value(
                    "File",
                    {"file_url": item.file},
                    ["file_type", "file_size"],
                    as_dict=True,
                )

                if db_file:
                    item.file_size = db_file.get('file_size') or item.file_size or 0
                    item.file_type = normalize_file_type(
                        item.file,
                        db_file.get('file_type') or item.file_type,
                    )
                else:
                    # File not found in database, try to infer from extension
                    item.file_type = normalize_file_type(item.file, item.file_type)

            except Exception as e:
                frappe.log_error(f"Error fetching file metadata: {str(e)}", "Media Validation Error")
                # Continue with existing values
                pass

    def validate_content_length(self):
        """Validate content length against platform limits"""
        from frappe_social.frappe_social.providers import get_provider

        if not self.platform or not self.content:
            return

        content_length = len(self.content or "")

        try:
            provider_class = get_provider(self.platform)
            max_length = getattr(provider_class, 'MAX_CONTENT_LENGTH', None)

            if max_length and content_length > max_length:
                frappe.throw(
                    _(f"Content exceeds {self.platform} limit of {max_length} characters"),
                    title=_("Content Too Long"),
                )
        except Exception as e:
            frappe.log_error(f"Error validating content length: {str(e)}", "Social Provider Error")

    def validate_media(self):
        """Validate media files against platform requirements"""
        from frappe_social.frappe_social.providers import get_provider

        if not self.platform or not self.media:
            return

        try:
            provider_class = get_provider(self.platform)
        except Exception as e:
            frappe.log_error(f"Error loading provider: {str(e)}", "Social Provider Error")
            return

        num_media = len(self.media)
        num_videos = 0

        max_media_count = getattr(provider_class, 'MAX_MEDIA_COUNT', 10)

        if num_media > max_media_count:
            frappe.throw(
                _(f"Too many media files for {self.platform}: {num_media} > {max_media_count}"),
                title=_("Too Many Media Files")
            )

        for media in self.media:
            file_type = (media.file_type or "").lower()
            file_size = media.file_size or 0

            is_image = "image" in file_type
            is_video = "video" in file_type

            if not (is_image or is_video):
                frappe.throw(
                    _(f"Unsupported media type '{file_type}' for {self.platform} (File: {media.file})"),
                    title=_("Invalid Media Type")
                )

            allowed_image_types = getattr(provider_class, 'ALLOWED_IMAGE_TYPES', [])
            allowed_video_types = getattr(provider_class, 'ALLOWED_VIDEO_TYPES', [])
            allowed_types = allowed_image_types if is_image else allowed_video_types

            # Auto-correct jpg to jpeg
            if is_image and "image/jpeg" in allowed_types and file_type == "image/jpg":
                media.file_type = "image/jpeg"
                file_type = "image/jpeg"

            if file_type not in allowed_types:
                frappe.throw(
                    _(f"Media type '{file_type}' is not allowed on {self.platform}. "
                      f"Allowed: {', '.join(allowed_types)}"),
                    title=_("Media Type Not Allowed")
                )

            max_image_size = getattr(provider_class, 'MAX_IMAGE_SIZE', 5 * 1024 * 1024)  # 5MB default
            max_video_size = getattr(provider_class, 'MAX_VIDEO_SIZE', 100 * 1024 * 1024)  # 100MB default
            max_size = max_image_size if is_image else max_video_size

            if file_size > max_size:
                size_mb = file_size / (1024 * 1024)
                max_mb = max_size / (1024 * 1024)
                frappe.throw(
                    _(f"File too large: {size_mb:.2f}MB > {max_mb:.2f}MB"),
                    title=_("File Too Large")
                )

            if is_video:
                num_videos += 1

            allows_multi_video = getattr(provider_class, 'ALLOWS_MULTI_VIDEO', False)
            if num_videos > 1 and not allows_multi_video:
                frappe.throw(
                    _(f"{self.platform} does not support multiple videos"),
                    title=_("Multiple Videos Not Supported")
                )

    def can_transition_to(self, new_status: str) -> bool:
        """Check if status transition is valid"""
        return new_status in self.VALID_TRANSITIONS.get(self.status, [])

    def set_status(self, new_status: str, commit: bool = False):
        """Set status with validation"""
        if self.can_transition_to(new_status):
            self.status = new_status
            self.save(ignore_permissions=True)
            if commit:
                frappe.db.commit()
        else:
            frappe.throw(
                _(f"Cannot change status from {self.status} to {new_status}"),
                title=_("Invalid Status Transition")
            )

    def validate_update_after_submit(self):
        """Allow status updates after submission"""
        if self.get_doc_before_save():
            old_status = self.get_doc_before_save().status
            if self.status != old_status:
                return

        super().validate_update_after_submit()

    # =====================================================
    # AD-SPECIFIC METHODS
    # =====================================================

    def build_ad_creative_payload(self) -> Dict:
        """
        Build Meta Ads Creative payload from Social Post data
        Returns:
            Dict: Complete payload for Meta Ads Creative API
        """
        if not self.is_ad:
            frappe.throw(_("This is not an ad post"), title=_("Invalid Operation"))

        # Get Facebook page ID
        page_id = self._get_facebook_page_id()
        if not page_id:
            frappe.throw(_("Facebook Page ID is required for ad creatives"), title=_("Missing Page ID"))

        # Get creative data from child table
        creative_name = self.post_name or f"Creative for {self.name}"
        link_url = ""
        cta_type = None
        caption = ""
        
        if self.ad_creative and len(self.ad_creative) > 0:
            creative_row = self.ad_creative[0]
            if creative_row.creative_name:
                creative_name = creative_row.creative_name
            link_url = creative_row.link_url or ""
            if creative_row.call_to_action:
                cta_type = self._map_cta_to_meta_format(creative_row.call_to_action)
            # Extract domain for caption
            if link_url:
                from urllib.parse import urlparse
                parsed = urlparse(link_url)
                caption = parsed.netloc or link_url

        # Validate link_url if provided
        if link_url and not self._is_valid_url(link_url):
            frappe.throw(_("Invalid link URL in creative"), title=_("Invalid URL"))

        # Get clean content for message
        clean_content = self._get_clean_content()
        
        # Ensure link_url has a valid value
        if not link_url or link_url.strip() == '':
            frappe.throw(_("Link URL is required for ad creatives"), title=_("Missing Link URL"))
        
        # Build link_data structure with required fields
        link_data = {
            "link": link_url,  # Required field
            "description": clean_content[:200] if clean_content else "Ad",  # Ensure not empty
            "caption": caption or link_url or "walue.biz"  # Use caption or fallback to link URL
        }

        # Add caption if we have it
        # if caption:
        #     link_data["caption"] = caption

        # Add call to action if provided
        if cta_type:
            link_data["call_to_action"] = {
                "type": cta_type
            }

        # Handle media - use 'picture' field with image URL
        if self.media and len(self.media) > 0:
            if len(self.media) == 1:
                # Single media
                media_item = self.media[0]
                file_type = (media_item.file_type or "").lower()

                if "image" in file_type:
                    # Single image - upload and get URL
                    image_url = self._upload_image_to_meta(media_item.file)
                    if image_url:
                        # Sanitize image URL - remove tracking parameters
                        clean_url = self._sanitize_image_url(image_url)
                        link_data["picture"] = image_url # ✅ Use 'picture' with URL
                elif "video" in file_type:
                    # Single video
                    video_id = self._upload_video_to_meta(media_item.file)
                    if video_id:
                        link_data["video_id"] = video_id
            else:
                # Multiple images (carousel)
                child_attachments = []
                for media_item in self.media:
                    image_url = self._upload_image_to_meta(media_item.file)
                    if image_url:
                        # Sanitize image URL
                        clean_url = self._sanitize_image_url(image_url)
                        child_attachments.append({
                            "picture": clean_url,  # ✅ Use 'picture' with URL
                            "link": link_url,
                            "description": self._get_clean_content()[:200] if self.content else ""
                        })

                if child_attachments:
                    link_data["child_attachments"] = child_attachments
                    link_data["multi_share_optimized"] = True

        # Build object_story_spec with required fields
        object_story_spec = {
            "page_id": page_id,
            "link_data": link_data,
            # "picture": image_url  # ✅ Use 'picture' with URL
        }

        # Build the complete creative payload with all required fields
        creative_payload = {
            "name": creative_name,
            "object_story_spec": object_story_spec,
        }

        frappe.log_error(
            message=json.dumps(creative_payload, indent=2),
            title=f"Ad Creative Payload - {self.name}"
        )

        return creative_payload

    def build_ad_payload(self, creative_id: str) -> Dict:
        """
        Build Meta Ad payload from Social Post data
        Args:
            creative_id: The ID of the created ad creative
        Returns:
            Dict: Complete payload for Meta Ad API
        """
        if not self.is_ad:
            frappe.throw(_("This is not an ad post"), title=_("Invalid Operation"))

        if not creative_id or not creative_id.strip():
            raise ValueError("Creative ID is required and cannot be empty")

        # Get ad set
        try:
            ad_set = frappe.get_doc('Ad Set', self.select_ad_set)
        except Exception as e:
            raise ValueError(f"Ad Set '{self.select_ad_set}' not found: {str(e)}")

        if not ad_set.adset_id or not ad_set.adset_id.strip():
            raise ValueError(f"Ad Set '{self.select_ad_set}' has not been created on Meta yet. Ensure the ad set is properly synced.")

        # Build ad payload
        ad_name = self.post_name or f"Ad for {self.name}"
        if not ad_name or not ad_name.strip():
            ad_name = f"Ad {self.name} {frappe.utils.now_datetime()}"

        ad_payload = {
            "name": ad_name,
            "adset_id": ad_set.adset_id,
            "creative": {
                "creative_id": creative_id
            },
            "status": "PAUSED"  # Create as paused initially
        }

        frappe.log_error(
            message=json.dumps(ad_payload, indent=2),
            title=f"Ad Payload - {self.name}"
        )

        return ad_payload

    def _get_facebook_page_id(self) -> str:
        """
        Get Facebook Page ID from selected page
        Returns:
            str: Facebook Page ID
        """
        if not self.selected_facebook_page:
            frappe.throw(
                _("Facebook Page is required for ad creation"),
                title=_("Missing Facebook Page")
            )

        # Get page ID from ad account integration
        ad_account = frappe.get_doc('Ads Account Integration', self.select_ad_account)
        for page in ad_account.fb_pages:
            if page.page_name == self.selected_facebook_page:
                return page.page_id

        frappe.throw(
            _("Could not find Page ID for selected Facebook Page"),
            title=_("Page ID Not Found")
        )

    def _get_page_access_token(self) -> str:
        """
        Get Facebook Page Access Token
        Returns:
            str: Page Access Token
        """
        ad_account = frappe.get_doc('Ads Account Integration', self.select_ad_account)

        # Get page access token
        page_access_token = ad_account.page_access_token

        if not page_access_token:
            # Fallback to account access token
            page_access_token = ad_account.access_token

        if not page_access_token:
            frappe.throw(
                _("No access token found for ad account"),
                title=_("Missing Access Token")
            )

        return page_access_token

    def _upload_image_to_meta(self, file_url: str) -> Optional[str]:
        """
        Upload image to Meta and return image URL
        Args:
            file_url: File URL from Frappe
        Returns:
            str: Image URL from Meta or None if failed
        """
        try:
            from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider

            # Get local file path
            file_path = frappe.get_site_path('public', file_url.lstrip('/'))
            if not os.path.exists(file_path):
                frappe.log_error(
                    message=f"File not found: {file_path}",
                    title="Image Upload Error"
                )
                return None

            # Upload via Meta Ads Provider
            provider = MetaAdsProvider(self.select_ad_account)
            result = provider.upload_image({"filename": file_path})

            if result.success and result.image_url:
                frappe.log_error(
                    message=f"Image uploaded successfully. URL: {result.image_url}",
                    title=f"Image Upload Success - {self.name}"
                )
                return result.image_url  # ✅ Return URL for 'picture' field
            else:
                frappe.log_error(
                    message=f"Upload failed: {result.error_message}",
                    title="Image Upload Error"
                )
                return None

        except Exception as e:
            frappe.log_error(
                message=f"Exception during image upload: {str(e)}\n{frappe.get_traceback()}",
                title="Image Upload Exception"
            )
            return None

    def _upload_video_to_meta(self, file_url: str) -> Optional[str]:
        """
        Upload video to Meta and return video ID
        Args:
            file_url: File URL from Frappe
        Returns:
            str: Video ID from Meta or None if failed
        """
        try:
            # Get local file path
            file_path = frappe.get_site_path('public', file_url.lstrip('/'))
            if not os.path.exists(file_path):
                frappe.log_error(
                    message=f"File not found: {file_path}",
                    title="Video Upload Error"
                )
                return None

            # TODO: Implement video upload via Meta API
            # Video upload is more complex and requires resumable upload
            # For now, return None and handle via image/carousel only
            frappe.log_error(
                message="Video upload not yet implemented",
                title="Video Upload Pending"
            )
            return None

        except Exception as e:
            frappe.log_error(
                message=f"Exception during video upload: {str(e)}\n{frappe.get_traceback()}",
                title="Video Upload Exception"
            )
            return None

    def _get_clean_content(self) -> str:
        """
        Get clean content text without HTML
        Returns:
            str: Plain text content
        """
        if not self.content:
            return ""

        # Remove HTML tags
        clean = re.sub('<.*?>', '', self.content)

        # Decode HTML entities
        clean = html.unescape(clean)

        # Remove extra whitespace
        clean = ' '.join(clean.split())

        return clean.strip()

    def _map_cta_to_meta_format(self, cta: str) -> str:
        """
        Map our CTA options to Meta's CTA types
        Args:
            cta: Our CTA value
        Returns:
            str: Meta CTA type
        """
        cta_mapping = {
            "Buy Now": "SHOP_NOW",
            "Shop Now": "SHOP_NOW",
            "Order Now": "ORDER_NOW",
            "Learn More": "LEARN_MORE",
            "Sign Up": "SIGN_UP",
            "Book Now": "BOOK_TRAVEL",
            "Download": "DOWNLOAD",
            "Contact Us": "CONTACT_US"
        }

        return cta_mapping.get(cta, "LEARN_MORE")  # Default to LEARN_MORE

    def _is_valid_url(self, url: str) -> bool:
        """
        Validate if URL is properly formatted
        Args:
            url: URL string to validate
        Returns:
            bool: True if valid, False otherwise
        """
        if not url:
            return True  # Empty is ok for optional fields
        
        # Basic URL validation
        url_pattern = r'^https?://[^\s/$.?#].[^\s]*$'
        return bool(re.match(url_pattern, url))

    def _sanitize_image_url(self, image_url: str) -> str:
        """
        Sanitize image URL by removing Facebook tracking parameters
        that might cause validation errors
        Args:
            image_url: Original image URL from Meta
        Returns:
            str: Sanitized URL
        """
        if not image_url:
            return image_url
        
        try:
            from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
            
            parsed = urlparse(image_url)
            params = parse_qs(parsed.query)
            
            # Keep only essential parameters, remove tracking/cdm params
            allowed_params = ['w', 'h', 'quality', 'format']
            filtered_params = {k: v for k, v in params.items() if k in allowed_params}
            
            # Reconstruct query string
            new_query = urlencode(filtered_params, doseq=True)
            new_parsed = parsed._replace(query=new_query)
            
            sanitized_url = urlunparse(new_parsed)
            
            frappe.log_error(
                message=f"Original URL: {image_url}\nSanitized URL: {sanitized_url}",
                title="Image URL Sanitization"
            )
            
            return sanitized_url
        except Exception as e:
            # If sanitization fails, return original URL
            frappe.log_error(
                message=f"Failed to sanitize image URL: {str(e)}",
                title="Image URL Sanitization Error"
            )
            return image_url

    def publish_as_ad(self):
        """
        Publish the social post as a Meta Ad
        Creates creative and ad on Meta
        """
        if not self.is_ad:
            frappe.throw(_("This is not an ad post"), title=_("Invalid Operation"))

        try:
            from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider

            # Validate required fields before proceeding
            if not self.select_ad_account:
                raise ValueError("Ads Account Integration is required")
            if not self.select_ad_set:
                raise ValueError("Ad Set is required")
            if not self.selected_facebook_page:
                raise ValueError("Facebook Page is required")
            if not self.ad_creative or len(self.ad_creative) == 0:
                raise ValueError("Ad Creative details are required")

            # Set status to Publishing
            self.status = "Publishing"
            self.save(ignore_permissions=True)
            frappe.db.commit()

            # Initialize provider
            try:
                provider = MetaAdsProvider(self.select_ad_account)
            except Exception as e:
                raise ValueError(f"Failed to initialize ads provider: {str(e)}")

            # Step 1: Build and create creative
            frappe.log_error(
                message="Starting ad creative creation",
                title=f"Ad Publishing Started - {self.name}"
            )

            # Get page access token for creative creation
            page_access_token = self._get_page_access_token()

            # Build creative payload
            try:
                creative_payload = self.build_ad_creative_payload()
            except Exception as e:
                raise ValueError(f"Failed to build creative payload: {str(e)}")

            # Validate creative payload
            if not creative_payload.get('object_story_spec', {}).get('page_id'):
                raise ValueError("Page ID is missing from creative payload")
            if not creative_payload.get('object_story_spec', {}).get('link_data'):
                raise ValueError("Link data is missing from creative payload")

            # Create creative
            creative_result = provider.create_creative(creative_payload, page_access_token)

            if not creative_result.success:
                raise Exception(f"Creative creation failed: {creative_result.error_message}")

            creative_id = creative_result.creative_id
            if not creative_id:
                raise ValueError("No creative ID returned from API")

            # Update creative row if exists
            if self.ad_creative and len(self.ad_creative) > 0:
                creative_row = self.ad_creative[0]
                frappe.db.set_value(
                    "Ad Creative",
                    creative_row.name,
                    "creative_id",
                    creative_id
                )

            frappe.log_error(
                message=f"Creative created: {creative_id}",
                title=f"Creative Success - {self.name}"
            )

            # Step 2: Build and create ad
            try:
                ad_payload = self.build_ad_payload(creative_id)
            except Exception as e:
                raise ValueError(f"Failed to build ad payload: {str(e)}")

            ad_result = provider.create_ad(ad_payload)

            if not ad_result.success:
                raise Exception(f"Ad creation failed: {ad_result.error_message}")

            ad_id = ad_result.ad_id
            if not ad_id:
                raise ValueError("No ad ID returned from API")

            # Update document with IDs
            self.ad_id = ad_id
            self.status = "Published"

            self.save(ignore_permissions=True)
            frappe.db.commit()

            frappe.log_error(
                message=f"Ad created successfully: {ad_id}\nCreative ID: {creative_id}",
                title=f"Ad Publishing Complete - {self.name}"
            )

            return {
                "success": True,
                "creative_id": creative_id,
                "ad_id": ad_id,
                "message": f"Ad published successfully with ID {ad_id}"
            }

        except ValueError as e:
            # Validation errors
            error_msg = str(e)
            frappe.log_error(
                message=f"Validation error: {error_msg}",
                title=f"Ad Publishing Validation Error - {self.name}"
            )
            self.status = "Failed"
            self.error_log = error_msg
            self.save(ignore_permissions=True)
            frappe.db.commit()
            return {
                "success": False,
                "error_message": error_msg,
                "error_type": "validation"
            }
        except Exception as e:
            # API or other errors
            error_msg = str(e)
            frappe.log_error(
                message=f"Ad publishing failed: {error_msg}\n{frappe.get_traceback()}",
                title=f"Ad Publishing Failed - {self.name}"
            )

            self.status = "Failed"
            self.error_log = error_msg
            self.save(ignore_permissions=True)
            frappe.db.commit()

            return {
                "success": False,
                "error_message": error_msg,
                "error_type": "api"
            }


# =====================================================
# WHITELISTED FUNCTIONS
# =====================================================

@frappe.whitelist()
def publish_ad(post_name):
    """
    Publish a social post as an ad
    """
    try:
        doc = frappe.get_doc("Social Post", post_name)

        # Validate it's an ad
        if not doc.is_ad:
            return {
                "success": False,
                "error_message": "This is not an ad post"
            }

        # Validate required ad fields
        required_fields = {
            'campagin': 'Campaign',
            'select_ad_account': 'Ads Account Integration',
            'select_ad_set': 'Ad Set',
            'selected_facebook_page': 'Facebook Pages'
        }

        for field, label in required_fields.items():
            if not doc.get(field):
                return {
                    "success": False,
                    "error_message": f"{label} is required for ad publishing"
                }

        # Call the publish_as_ad method
        result = doc.publish_as_ad()

        return result

    except Exception as e:
        frappe.log_error(
            message=f"Ad publishing error: {str(e)}\n{frappe.get_traceback()}",
            title=f"Ad Publish Failed - {post_name}"
        )

        return {
            "success": False,
            "error_message": str(e)
        }


@frappe.whitelist()
def get_platforms_for_organization(organization, is_ad=0):
    """Get available platforms for an organization"""
    if not organization:
        return []
    
    # Determine which doctype to query based on mode
    if int(is_ad):
        # For ads mode - use Ads Account Integration with 'organisation' field (British spelling)
        platforms = frappe.db.get_all(
            "Ads Account Integration",
            filters={
                "organisation": organization,  # Note: British spelling with 's'
                "enabled": 1,
                "connection_status": "Connected"
            },
            pluck="platform",
            distinct=True,
            order_by="platform asc",
        )
    else:
        # For normal posts mode - use Social Integration with 'organization' field
        platforms = frappe.db.get_all(
            "Social Integration",
            filters={
                "organization": organization,  # American spelling
                "enabled": 1,
                "connection_status": "Connected"
            },
            pluck="platform",
            distinct=True,
            order_by="platform asc",
        )
    
    return platforms or []


@frappe.whitelist()
def get_facebook_pages_for_account(ad_account):
    """
    Get Facebook pages for a specific ad account
    """
    if not ad_account:
        return []

    try:
        doc = frappe.get_doc('Ads Account Integration', ad_account)

        if not doc.fb_pages:
            return []

        pages = []
        for page in doc.fb_pages:
            pages.append({
                'page_name': page.page_name,
                'page_id': page.page_id
            })

        return pages

    except Exception as e:
        frappe.log_error(f"Error fetching Facebook pages: {str(e)}", "Facebook Pages Error")
        return []
