# ad_creative.py
# Copyright (c) 2026, Abhishek and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants – Meta Marketing API v24.0
# ---------------------------------------------------------------------------

CTA_MAP = {
    "Learn More": "LEARN_MORE",
    "Shop Now":   "SHOP_NOW",
    "Sign Up":    "SIGN_UP",
}

DESTINATION_MAP = {
    "Website":          "WEBSITE",
    "Instant Experience": "INSTANT_EXPERIENCE",
    "Call":             "PHONE_CALL",
    "Messaging Apps":   "MESSENGER",
}

BROWSER_ADDON_CTA_MAP = {
    "Messenger": "MESSAGE_PAGE",
    "Whatsapp":  "WHATSAPP_MESSAGE",
}

FORMAT_MAP = {
    "Single Image or Video": "single",
    "Carousel":              "carousel",
    "Collection":            "collection",
}


# ---------------------------------------------------------------------------
# Document class
# ---------------------------------------------------------------------------

class AdCreative(Document):
    """Ad Creative DocType – builds Facebook Marketing API v24.0 payloads."""

    def validate(self):
        if not self.creative_name:
            frappe.throw(_("Creative Name is required"))

        if not self.select_facebook_page:
            frappe.throw(_("Select Facebook Page is required"))

        if not self.website_url and self.destination == "Website":
            frappe.throw(_("Website URL is required when Destination is Website"))

        if self.website_url:
            self._validate_url(self.website_url)

    # ------------------------------------------------------------------
    # Public helper
    # ------------------------------------------------------------------

    def get_fb_payload(self) -> dict:
        """
        Build and return the payload for:
          POST https://graph.facebook.com/v24.0/act_{ad_account_id}/adcreatives

        Returns a dict ready to be JSON-serialised and sent to Meta.
        """
        fmt = FORMAT_MAP.get(self.format, "single")

        if fmt == "carousel":
            payload = self._build_carousel_payload()
        elif fmt == "collection":
            payload = self._build_collection_payload()
        else:
            payload = self._build_single_payload()

        # ── Multi-advertiser ads ───────────────────────────────────────
        if self.multi_advertiser_ads:
            payload["multi_advertiser_ads"] = True

        # ── Flexible media (Advantage+ creative) ──────────────────────
        if self.flexible_media:
            payload["degrees_of_freedom_spec"] = {
                "creative_features_spec": {
                    "standard_enhancements": {"enroll_status": "OPT_IN"}
                }
            }

        logger.debug("Ad Creative payload: %s", payload)
        return payload

    # ------------------------------------------------------------------
    # Format builders
    # ------------------------------------------------------------------

    def _build_single_payload(self) -> dict:
        """Single Image or Video creative."""
        link_data = self._base_link_data()

        # Attach image hash or video_id from the single-media field
        if self.medi:
            file_doc = self._get_file_meta(self.medi)
            if file_doc and file_doc.get("is_video"):
                return self._wrap_video_story(file_doc["file_url"], link_data)
            if file_doc:
                link_data["image_hash"] = file_doc.get("image_hash", "")

        return {
            "name": self.creative_name,
            "object_story_spec": {
                "page_id": self.select_facebook_page,
                **self._instagram_actor(),
                "link_data": link_data,
            },
        }

    def _build_carousel_payload(self) -> dict:
        """Carousel creative – builds child_attachments from the media child table."""
        child_attachments = []

        for row in (self.media or []):
            attachment = {
                "link":        row.get("link_url") or self.website_url or "",
                "name":        row.get("headline") or self.headline or "",
                "description": row.get("description") or "",
            }
            if row.get("image_hash"):
                attachment["image_hash"] = row["image_hash"]
            elif row.get("video_id"):
                attachment["video_id"] = row["video_id"]

            cta_type = CTA_MAP.get(self.call_to_action)
            if cta_type:
                attachment["call_to_action"] = {
                    "type":  cta_type,
                    "value": {"link": attachment["link"]},
                }

            child_attachments.append(attachment)

        if not child_attachments:
            frappe.throw(_("Carousel format requires at least one media row"))

        link_data = {
            "message":           self._strip_html(self.primary_text),
            "link":              self.website_url or "",
            "child_attachments": child_attachments,
            "multi_share_optimized": True,
            "multi_share_end_card":  False,
        }

        return {
            "name": self.creative_name,
            "object_story_spec": {
                "page_id": self.select_facebook_page,
                **self._instagram_actor(),
                "link_data": link_data,
            },
        }

    def _build_collection_payload(self) -> dict:
        """
        Collection creative – requires a cover image/video + instant experience.
        Falls back to a carousel-style payload when no instant experience URL
        is configured, so the creative can still be saved for later wiring.
        """
        # A collection ad needs an Instant Experience (canvas URL).
        # We surface that via the website_url field when destination is
        # "Instant Experience"; otherwise we degrade gracefully.
        instant_exp_url = (
            self.website_url
            if self.destination == "Instant Experience"
            else None
        )

        cover = {}
        if self.media:
            first = self.media[0]
            if first.get("image_hash"):
                cover["image_hash"] = first["image_hash"]
            elif first.get("video_id"):
                cover["video_id"] = first["video_id"]

        template_url_spec = {}
        if instant_exp_url:
            template_url_spec = {
                "web": {"url": instant_exp_url},
            }

        payload = {
            "name": self.creative_name,
            "object_story_spec": {
                "page_id": self.select_facebook_page,
                **self._instagram_actor(),
                "link_data": {
                    "link":    instant_exp_url or self.website_url or "",
                    "message": self._strip_html(self.primary_text),
                    "name":    self.headline or "",
                    **cover,
                },
            },
        }

        if template_url_spec:
            payload["template_url_spec"] = template_url_spec

        return payload

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _base_link_data(self) -> dict:
        """Build the common link_data block shared by single/collection."""
        cta_type = CTA_MAP.get(self.call_to_action)

        # Handle browser add-on CTA override (Messenger / WhatsApp click)
        addon_cta = BROWSER_ADDON_CTA_MAP.get(self.browser_addons)
        resolved_cta = addon_cta or cta_type

        link_data: dict = {
            "link":        self.website_url or "",
            "message":     self._strip_html(self.primary_text),
            "name":        self.headline or "",
            "description": self.description or "",
            "caption":     self.display_link or "",
        }

        if resolved_cta:
            link_data["call_to_action"] = {
                "type":  resolved_cta,
                "value": {"link": self.website_url or ""},
            }

        return {k: v for k, v in link_data.items() if v}  # drop empty strings

    def _wrap_video_story(self, video_url: str, link_data: dict) -> dict:
        """Switch to video_data spec when the attached media is a video."""
        video_data = {
            "video_id":    "",          # populated after upload via /advideos
            "title":       self.headline or "",
            "message":     self._strip_html(self.primary_text),
            "link_description": self.description or "",
        }

        cta_type = CTA_MAP.get(self.call_to_action)
        if cta_type:
            video_data["call_to_action"] = {
                "type":  cta_type,
                "value": {"link": self.website_url or ""},
            }

        return {
            "name": self.creative_name,
            "object_story_spec": {
                "page_id": self.select_facebook_page,
                **self._instagram_actor(),
                "video_data": {k: v for k, v in video_data.items() if v},
            },
        }

    def _instagram_actor(self) -> dict:
        """Return instagram_actor_id block when an IG account is selected."""
        actors = {}
        if self.select_instagram_account:
            actors["instagram_actor_id"] = self.select_instagram_account
        # Threads actor is not yet a standard Meta API field; kept for future use
        return actors

    def _get_file_meta(self, file_url: str) -> dict | None:
        """Resolve a Frappe File URL to useful metadata (type, hash)."""
        try:
            file_doc = frappe.get_doc("File", {"file_url": file_url})
            ext = (file_url or "").rsplit(".", 1)[-1].lower()
            return {
                "file_url":   file_url,
                "is_video":   ext in ("mp4", "mov", "avi", "mkv"),
                "image_hash": getattr(file_doc, "image_hash", ""),
            }
        except frappe.DoesNotExistError:
            return None

    @staticmethod
    def _strip_html(text: str | None) -> str:
        """Strip HTML tags coming from the Text Editor field."""
        if not text:
            return ""
        import re
        return re.sub(r"<[^>]+>", "", text).strip()

    @staticmethod
    def _validate_url(url: str):
        if not url.startswith(("http://", "https://")):
            frappe.throw(_("URL must start with http:// or https://"))


# ---------------------------------------------------------------------------
# Standalone builder (mirrors campaign.py pattern – callable from hooks/API)
# ---------------------------------------------------------------------------

def build_ad_creative_payload(doc) -> dict:
    """
    Convenience wrapper so external callers (hooks, whitelisted methods, tests)
    can obtain the payload without instantiating AdCreative directly.

    Usage:
        from frappe_social.ads_manager.doctype.ad_creative.ad_creative import (
            build_ad_creative_payload,
        )
        payload = build_ad_creative_payload(doc)
        result  = provider.create_ad_creative(payload)
    """
    creative = AdCreative("Ad Creative")

    # Copy all relevant fields from the caller's doc onto our instance
    _FIELDS = [
        "creative_name", "select_facebook_page", "select_instagram_account",
        "select_threads_account", "format", "destination", "website_url",
        "display_link", "browser_addons", "medi", "media", "primary_text",
        "headline", "description", "call_to_action", "multi_advertiser_ads",
        "flexible_media", "add_music",
    ]
    for field in _FIELDS:
        setattr(creative, field, getattr(doc, field, None))

    return creative.get_fb_payload()


@frappe.whitelist()
def get_facebook_pages(ad_account: str) -> list:
    """
    Retrieve all Facebook pages associated with the selected ad account.
    
    Args:
        ad_account (str): Name of the Ads Account Integration document
    
    Returns:
        list: List of dictionaries containing page_id and page_name for each Facebook page
    """
    try:
        if not ad_account:
            return []
        
        # Get the Ads Account Integration document
        integration = frappe.get_doc("Ads Account Integration", ad_account)
        
        # Extract Facebook pages from meta_assets child table
        facebook_pages = []
        if integration.meta_assets:
            for asset in integration.meta_assets:
                # Only include entries with platform = "Facebook"
                if asset.get("platform") == "Facebook":
                    facebook_pages.append({
                        "page_id": asset.get("page_id"),
                        "page_name": asset.get("page_name"),
                        "platform": asset.get("platform"),
                    })
        
        logger.info(f"Retrieved {len(facebook_pages)} Facebook pages for ad account: {ad_account}")
        return facebook_pages
    
    except frappe.DoesNotExistError:
        logger.error(f"Ad account not found: {ad_account}")
        frappe.throw(_("Ad account not found"))
    except Exception as e:
        logger.error(f"Error retrieving Facebook pages: {str(e)}")
        frappe.throw(_("Error retrieving Facebook pages: {0}").format(str(e)))

@frappe.whitelist()
def get_instagram_account(ad_account: str) -> list:
    """
    Retrieve all Instagram Account associated with the selected ad account.
    
    Args:
        ad_account (str): Name of the Ads Account Integration document
    
    Returns:
        list: List of dictionaries containing page_id and page_name (username) for each Instagram account
    """
    try:
        if not ad_account:
            return []
        
        # Get the Ads Account Integration document
        integration = frappe.get_doc("Ads Account Integration", ad_account)
        
        # Extract Instagram Account from meta_assets child table
        instagram_account = []
        if integration.meta_assets:
            for asset in integration.meta_assets:
                # Only include entries with platform = "Instagram"
                if asset.get("platform") == "Instagram":
                    instagram_account.append({
                        "page_id": asset.get("page_id"),
                        "page_name": asset.get("username"),
                        # "username": asset.get("username"),
                        "platform": asset.get("platform"),
                    })
        
        logger.info(f"Retrieved {len(instagram_account)} Instagram Account(s) for ad account: {ad_account}")
        return instagram_account
    
    except frappe.DoesNotExistError:
        logger.error(f"Ad account not found: {ad_account}")
        frappe.throw(_("Ad account not found"))
    except Exception as e:
        logger.error(f"Error retrieving Instagram Account: {str(e)}")
        frappe.throw(_("Error retrieving Instagram Account: {0}").format(str(e)))


@frappe.whitelist()
def get_existing_posts(ad_account: str, page_id: str, limit: int = 50) -> list:
    """
    Retrieve existing posts from a Facebook page for use in ads.
    
    Args:
        ad_account (str): Name of the Ads Account Integration document
        page_id (str): Facebook Page ID
        limit (int): Maximum number of posts to retrieve (default 50)
    
    Returns:
        list: List of dictionaries containing post details (id, message, media_url, etc.)
    """
    import requests
    from datetime import datetime
    
    try:
        if not ad_account or not page_id:
            return []
        
        # Get the Ads Account Integration document
        integration = frappe.get_doc("Ads Account Integration", ad_account)
        
        # Find the page access token for the selected page
        page_access_token = None
        if integration.meta_assets:
            for asset in integration.meta_assets:
                if asset.get("platform") == "Facebook" and asset.get("page_id") == page_id:
                    page_access_token = asset.get("page_access_token")
                    break
        
        if not page_access_token:
            logger.error(f"No page access token found for page {page_id}")
            frappe.throw(_("Page access token not found. Please reconnect the ad account."))
        
        # Get API settings
        settings = frappe.get_single("Social Settings")
        api_version = settings.meta_api_version or "v24.0"
        
        # Fetch posts from Meta Graph API
        url = f"https://graph.facebook.com/{api_version}/{page_id}/posts"
        params = {
            "access_token": page_access_token,
            "fields": "id,message,created_time,type,picture,permalink,status_type",
            "limit": limit,
            "since": (datetime.now().replace(day=1).isoformat()),  # Posts from this month
        }
        
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        posts = []
        if data.get("data"):
            for post in data["data"]:
                post_id = post.get("id", "")
                
                # Extract post data
                post_obj = {
                    "post_id": post_id,
                    "message": post.get("message", "") or post.get("story", ""),
                    "media_url": post.get("picture", ""),
                    "source": post.get("status_type", "").replace("_", " ").title() if post.get("status_type") else "Feed",
                    "media_type": post.get("type", "").title() if post.get("type") else "Status",
                    "created_date": parse_date(post.get("created_time", "")),
                    "permalink": post.get("permalink", ""),
                }
                
                # Only include posts with messages (exclude blank/system posts)
                if post_obj["message"]:
                    posts.append(post_obj)
        
        logger.info(f"Retrieved {len(posts)} posts from Facebook page {page_id}")
        return posts
    
    except requests.RequestException as e:
        logger.error(f"API request failed while fetching posts: {str(e)}")
        frappe.throw(_("Failed to fetch posts from Facebook. Please check your connection."))
    except frappe.DoesNotExistError:
        logger.error(f"Ad account not found: {ad_account}")
        frappe.throw(_("Ad account not found"))
    except Exception as e:
        logger.error(f"Error retrieving posts: {str(e)}")
        frappe.throw(_("Error retrieving posts: {0}").format(str(e)))


def parse_date(date_string: str) -> str:
    """Parse and format date string from Meta API."""
    if not date_string:
        return ""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(date_string.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y")
    except:
        return date_string

# EXAMPLE_SINGLE_IMAGE_PAYLOAD = {
#     "name": "Summer Sale – Single Image",
#     "object_story_spec": {
#         "page_id": "123456789",
#         "instagram_actor_id": "987654321",          # omit if no IG account
#         "link_data": {
#             "link":        "https://example.com/summer-sale",
#             "message":     "Grab the best deals this summer!",
#             "name":        "Summer Sale is Live",
#             "description": "Up to 50% off on selected items.",
#             "caption":     "example.com",
#             "image_hash":  "<HASH_FROM_ADIMAGES_UPLOAD>",
#             "call_to_action": {
#                 "type":  "SHOP_NOW",
#                 "value": {"link": "https://example.com/summer-sale"},
#             },
#         },
#     },
#     # Optional Advantage+ creative enhancements
#     "degrees_of_freedom_spec": {
#         "creative_features_spec": {
#             "standard_enhancements": {"enroll_status": "OPT_IN"},
#         },
#     },
# }

# EXAMPLE_CAROUSEL_PAYLOAD = {
#     "name": "Product Showcase – Carousel",
#     "object_story_spec": {
#         "page_id": "123456789",
#         "link_data": {
#             "message": "Check out our top products!",
#             "link":    "https://example.com",
#             "multi_share_optimized": True,
#             "multi_share_end_card":  False,
#             "child_attachments": [
#                 {
#                     "link":        "https://example.com/product-1",
#                     "name":        "Product One",
#                     "description": "Best seller",
#                     "image_hash":  "<HASH_1>",
#                     "call_to_action": {
#                         "type":  "SHOP_NOW",
#                         "value": {"link": "https://example.com/product-1"},
#                     },
#                 },
#                 {
#                     "link":        "https://example.com/product-2",
#                     "name":        "Product Two",
#                     "description": "New arrival",
#                     "image_hash":  "<HASH_2>",
#                     "call_to_action": {
#                         "type":  "SHOP_NOW",
#                         "value": {"link": "https://example.com/product-2"},
#                     },
#                 },
#             ],
#         },
#     },
# }

# EXAMPLE_VIDEO_PAYLOAD = {
#     "name": "Brand Story – Video",
#     "object_story_spec": {
#         "page_id": "123456789",
#         "instagram_actor_id": "987654321",
#         "video_data": {
#             "video_id":         "<VIDEO_ID_FROM_ADVIDEOS_UPLOAD>",
#             "title":            "Our Brand Story",
#             "message":          "Watch how we got started.",
#             "link_description": "Learn more about us.",
#             "call_to_action": {
#                 "type":  "LEARN_MORE",
#                 "value": {"link": "https://example.com/about"},
#             },
#         },
#     },
# }