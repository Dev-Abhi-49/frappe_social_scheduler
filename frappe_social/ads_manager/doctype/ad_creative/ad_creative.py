# ad_creative.py
# Copyright (c) 2026, Abhishek and contributors
# For license information, please see license.txt

"""
Ad Creative DocType – builds and submits Meta Marketing API v25.0 payloads.

Key fixes over the previous version
─────────────────────────────────────
1.  Page-ID / Instagram-actor-ID extraction
    The Select fields store "Page Name (123456789)" – the raw value must NOT
    be sent to Meta.  _extract_id() peels the numeric ID off the end.

2.  CTA values are already Meta API strings
    The Frappe Select options (LEARN_MORE, SHOP_NOW …) are identical to Meta's
    enum values, so no mapping is needed – they are passed through directly.
    The old CTA_MAP only covered 3 values; removed.

3.  "Use existing post" support
    When select_ad_type == "Use existing post" the payload must use
    object_story_id (= "<page_id>_<post_id>") instead of object_story_spec.

4.  Optional top-level fields included
    applink_treatment, authorization_category,
    branded_content_sponsor_page_id, bundle_folder_id.

5.  Ad-label IDs wired up from the ad_lables child table.

6.  image_hash vs picture
    If only a Frappe File URL is available (no hash), the URL is sent as
    'picture' (publicly accessible URL).  When an image_hash is already
    stored on the file doc it is preferred.

7.  Video creative: video_id is required
    _wrap_video_story() now raises a clear error when no video_id is available
    rather than silently sending an empty string.

8.  create_creative_on_meta() whitelisted method
    Saves the creative_id back to the document after a successful API call.

9.  Clean empty-value pruning
    All dict builders strip keys whose value is empty string / None / [].
"""

import re
import frappe
from frappe import _
from frappe.model.document import Document
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

VIDEO_EXTENSIONS = {"mp4", "mov", "avi", "mkv", "webm", "m4v"}

BROWSER_ADDON_CTA_MAP = {
    "Messenger": "MESSAGE_PAGE",
    "Whatsapp":  "WHATSAPP_MESSAGE",
}

DESTINATION_MAP = {
    "Website":              "WEBSITE",
    "Instant Experience":   "INSTANT_EXPERIENCE",
    "Call":                 "PHONE_CALL",
    "Messaging Apps":       "MESSENGER",
}


# ─────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────────────────────────────────────

def _extract_id(select_value: str) -> str:
    """
    Select fields store "Display Name (numeric_id)".
    Return just the numeric_id, or the raw value if the pattern does not match.

    Examples
    --------
    "My Page (123456789)"  →  "123456789"
    "123456789"            →  "123456789"
    ""                     →  ""
    """
    if not select_value:
        return ""
    match = re.search(r"\((\d+)\)\s*$", select_value)
    if match:
        return match.group(1)
    # Might already be a bare ID
    return select_value.strip()


def _strip_html(text: str | None) -> str:
    """Strip HTML tags produced by the Text Editor field."""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", "", text).strip()


def _clean(d: dict) -> dict:
    """Remove keys whose value is None, empty string, or empty list/dict."""
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def _validate_url(url: str, label: str = "URL"):
    if url and not url.startswith(("http://", "https://")):
        frappe.throw(_(f"{label} must start with http:// or https://"))


# ─────────────────────────────────────────────────────────────────────────────
# Document class
# ─────────────────────────────────────────────────────────────────────────────

class AdCreative(Document):
    """Ad Creative DocType – builds Facebook Marketing API v25.0 payloads."""

    # ------------------------------------------------------------------
    # Frappe lifecycle hooks
    # ------------------------------------------------------------------

    def validate(self):
        if not self.creative_name:
            frappe.throw(_("Creative Name is required"))

        if not self.select_facebook_page:
            frappe.throw(_("A Facebook Page must be selected"))

        if self.destination == "Website" and not self.website_url:
            frappe.throw(_("Website URL is required when Destination is Website"))

        if self.website_url:
            _validate_url(self.website_url, "Website URL")

        if self.display_link:
            _validate_url(self.display_link, "Display link")

        # "Use existing post" requires a selected post
        if self.select_ad_type == "Use existing post" and not self.selected_post_id:
            frappe.throw(_("Please select an existing post via the 'Browse Posts' button"))

        # Warn if using ngrok (common during development but unreliable for production APIs)
        if self.medi:
            file_url = self.medi or ""
            if "ngrok" in file_url.lower():
                frappe.warn(_(
                    "⚠️  NGROK URL Detected\n\n"
                    "Your image is hosted on an ngrok domain. "
                    "While this works for development, ngrok URLs are often:\n"
                    "- Rate-limited by external APIs like Meta\n"
                    "- Blocked by firewalls\n"
                    "- Unstable for production use\n\n"
                    "For best results, use a real domain or public IP address."
                ))


    # ------------------------------------------------------------------
    # Public payload builder
    # ------------------------------------------------------------------

    def get_fb_payload(self) -> dict:
        """
        Build the full payload for:
          POST https://graph.facebook.com/v25.0/act_{ad_account_id}/adcreatives

        Returns a dict ready to be JSON-serialised and sent to Meta.
        """
        # ── Existing post (object_story_id path) ─────────────────────
        if self.select_ad_type == "Use existing post":
            return self._build_existing_post_payload()

        # ── Create-ad paths ──────────────────────────────────────────
        fmt = (self.format or "Single Image or Video").strip()

        if fmt == "Carousel":
            payload = self._build_carousel_payload()
        elif fmt == "Collection":
            payload = self._build_collection_payload()
        else:
            payload = self._build_single_payload()

        # ── Optional top-level fields ────────────────────────────────
        if self.multi_advertiser_ads:
            payload["multi_advertiser_ads"] = True

        if self.flexible_media:
            payload["degrees_of_freedom_spec"] = {
                "creative_features_spec": {
                    "standard_enhancements": {"enroll_status": "OPT_IN"}
                }
            }

        if self.applink_treatment and self.applink_treatment != "automatic":
            payload["applink_treatment"] = self.applink_treatment

        if self.authorization_category and self.authorization_category != "NONE":
            payload["authorization_category"] = self.authorization_category

        if self.branded_content_sponsor_page_id:
            payload["branded_content_sponsor_page_id"] = self.branded_content_sponsor_page_id

        if self.bundle_folder_id:
            payload["bundle_folder_id"] = self.bundle_folder_id

        # ── Ad labels ────────────────────────────────────────────────
        ad_label_ids = self._get_ad_label_ids()
        if ad_label_ids:
            payload["adlabels"] = [{"id": lid} for lid in ad_label_ids]

        logger.debug("Ad Creative payload: %s", payload)
        return payload

    # ------------------------------------------------------------------
    # Format builders
    # ------------------------------------------------------------------

    def _build_existing_post_payload(self) -> dict:
        """
        Use an existing Facebook Page post as the ad creative.
        Endpoint expects object_story_id = "<page_id>_<post_id>".
        """
        page_id = _extract_id(self.select_facebook_page)
        post_id = (self.selected_post_id or "").strip()

        if not post_id:
            frappe.throw(_("No post selected. Use 'Browse Posts' to pick one."))

        # Meta accepts bare post_id or the full compound ID
        object_story_id = (
            post_id if "_" in post_id else f"{page_id}_{post_id}"
        )

        payload = _clean({
            "name":             self.creative_name,
            "object_story_id":  object_story_id,
        })

        # Optional Instagram actor
        instagram_id = _extract_id(self.select_instagram_account or "")
        if instagram_id:
            payload["instagram_actor_id"] = instagram_id

        return payload

    def _build_single_payload(self) -> dict:
        """
        Single Image or Video creative.
        
        IMAGE HANDLING STRATEGY:
        - For single images: use 'picture' field with public URL
          Meta downloads the image from the URL and caches it
        - URL must be publicly accessible (not localhost, not /private/files/)
        - Meta will reject with error 1885183 if URL is inaccessible or has params
        
        VIDEO HANDLING:
        - Videos require video_id (from /advideos endpoint)
        - Thumbnail can be specified via 'image_url' if needed
        
        Reference: https://developers.facebook.com/docs/marketing-api/reference/ad-creative/
        """
        page_id = _extract_id(self.select_facebook_page)
        link_data = self._base_link_data()

        if self.medi:
            file_meta = self._get_file_meta(self.medi)
            if file_meta:
                if file_meta["is_video"]:
                    if not file_meta.get("video_id"):
                        frappe.throw(_(
                            "Video must be uploaded to Meta via /advideos before creating a creative. "
                            "Store the returned video_id in the File document."
                        ))
                    return self._wrap_video_story(file_meta["video_id"], link_data, page_id)

                # Single image — pass 'picture' (public URL) to Meta.
                # Meta downloads the image from this URL when rendering the ad.
                # The URL must be publicly reachable (not localhost / private files).
                logger.info(f"Processing single image: {file_meta['file_url']}")
                public_url = self._to_public_url(file_meta["file_url"])
                
                if public_url:
                    # ⚠️  Warn if using ngrok
                    if "ngrok" in public_url.lower():
                        logger.warning(
                            "⚠️  NGROK URL DETECTED - This is causing error 1885183\n"
                            "   Ngrok domains are rate-limited by production APIs like Meta.\n"
                            "   \n"
                            "   SOLUTIONS:\n"
                            "   1. Deploy to a real server/domain (best)\n"
                            "   2. Use AWS S3, Cloudflare, or similar CDN\n"
                            "   3. Use a proper public IP + domain\n"
                            "   \n"
                            "   Ngrok is great for development but NOT for production APIs."
                        )
                    
                    logger.info(f"✓ Using picture URL: {public_url}")
                    link_data["picture"] = public_url
                    
                    # Validate the URL is actually accessible
                    is_accessible = self._validate_url_accessible(public_url)
                    if not is_accessible:
                        logger.warning(f"⚠ URL may not be accessible to Meta: {public_url}")
                else:
                    # URL is localhost or a private Frappe file — Meta cannot reach it.
                    # Raise a clear error so the developer knows exactly what to fix
                    # instead of getting a cryptic 1885183 from Meta.
                    frappe.throw(_(
                        "The attached image cannot be accessed by Meta: '{0}'. "
                        "Image URLs must be publicly reachable (not localhost or /private/files/). "
                        "Please host the image on a public URL and re-attach it."
                    ).format(file_meta["file_url"]))

        story_spec = _clean({
            "page_id":             page_id,
            "instagram_actor_id":  _extract_id(self.select_instagram_account or ""),
            "link_data":           _clean(link_data),
        })

        payload = _clean({
            "name":               self.creative_name,
            "object_story_spec":  story_spec,
        })
        
        logger.info(f"Final single-image payload picture URL: {link_data.get('picture')}")
        return payload

    def _build_carousel_payload(self) -> dict:
        """
        Carousel creative – multiple cards with images and/or videos.
        
        IMAGE HANDLING STRATEGY FOR CAROUSEL:
        - Use 'image_hash' for images (from Meta's image library)
        - Or use 'picture' field with public URL (Meta downloads & caches)
        - image_hash is preferred when available (no download latency)
        
        VIDEO HANDLING:
        - Use 'video_id' (from /advideos endpoint)
        - Each card can have either image_hash OR video_id OR picture
        
        CAROUSEL STRUCTURE:
        - Each card is an 'attachment' in child_attachments array
        - All cards share the same base link
        - Each card can have custom name, description, link, CTA
        
        Reference: https://developers.facebook.com/docs/marketing-api/reference/ad-creative/
        """
        page_id = _extract_id(self.select_facebook_page)
        child_attachments = []

        for row in (self.media or []):
            card_link = row.get("link_url") or self.website_url or ""
            attachment = _clean({
                "link":        card_link,
                "name":        row.get("headline") or self.headline or "",
                "description": row.get("description") or "",
            })

            # Media (image_hash preferred, then video_id)
            if row.get("image_hash"):
                attachment["image_hash"] = row["image_hash"]
            elif row.get("video_id"):
                attachment["video_id"] = row["video_id"]

            # CTA per card
            cta_type = self._resolve_cta()
            if cta_type and card_link:
                attachment["call_to_action"] = {
                    "type":  cta_type,
                    "value": {"link": card_link},
                }

            child_attachments.append(attachment)

        if not child_attachments:
            frappe.throw(_("Carousel format requires at least one media row in the Media table"))

        link_data = _clean({
            "message":               _strip_html(self.primary_text),
            "link":                  self.website_url or "",
            "child_attachments":     child_attachments,
            "multi_share_optimized": True,
            "multi_share_end_card":  False,
        })

        story_spec = _clean({
            "page_id":            page_id,
            "instagram_actor_id": _extract_id(self.select_instagram_account or ""),
            "link_data":          link_data,
        })

        return _clean({
            "name":              self.creative_name,
            "object_story_spec": story_spec,
        })

    def _build_collection_payload(self) -> dict:
        """
        Collection creative – cover image/video + Instant Experience URL.
        
        COLLECTION FORMAT:
        - Requires cover image (image_hash preferred) or video
        - Launches an Instant Experience (full-screen web view) when clicked
        - Supports multiple products/items in the Instant Experience
        
        IMAGE HANDLING:
        - Cover uses image_hash (preferred) or video_id
        - Falls back gracefully if no Instant Experience URL configured
        
        Reference: https://developers.facebook.com/docs/marketing-api/reference/ad-creative/
        """
        page_id = _extract_id(self.select_facebook_page)
        instant_exp_url = (
            self.website_url if self.destination == "Instant Experience" else None
        )

        cover = {}
        if self.media:
            first = self.media[0]
            if first.get("image_hash"):
                cover["image_hash"] = first["image_hash"]
            elif first.get("video_id"):
                cover["video_id"] = first["video_id"]

        link_data = _clean({
            "link":    instant_exp_url or self.website_url or "",
            "message": _strip_html(self.primary_text),
            "name":    self.headline or "",
            **cover,
        })

        story_spec = _clean({
            "page_id":            page_id,
            "instagram_actor_id": _extract_id(self.select_instagram_account or ""),
            "link_data":          link_data,
        })

        payload = _clean({
            "name":              self.creative_name,
            "object_story_spec": story_spec,
        })

        if instant_exp_url:
            payload["template_url_spec"] = {"web": {"url": instant_exp_url}}

        return payload

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _base_link_data(self) -> dict:
        """Common link_data block for single / video formats."""
        cta_type = self._resolve_cta()

        link_data = {
            "link":        self.website_url or "",
            "message":     _strip_html(self.primary_text),
            "name":        self.headline or "",
            "description": self.description or "",
            "caption":     self.display_link or "",
        }

        if cta_type and self.website_url:
            link_data["call_to_action"] = {
                "type":  cta_type,
                "value": {"link": self.website_url},
            }

        return link_data  # _clean() applied by caller

    def _wrap_video_story(self, video_id: str, link_data: dict, page_id: str) -> dict:
        """Switch to video_data spec when the attached media is a video."""
        cta_type = self._resolve_cta()

        video_data: dict = _clean({
            "video_id":         video_id,
            "title":            self.headline or "",
            "message":          _strip_html(self.primary_text),
            "link_description": self.description or "",
        })

        if cta_type and self.website_url:
            video_data["call_to_action"] = {
                "type":  cta_type,
                "value": {"link": self.website_url},
            }

        story_spec = _clean({
            "page_id":            page_id,
            "instagram_actor_id": _extract_id(self.select_instagram_account or ""),
            "video_data":         video_data,
        })

        return _clean({
            "name":              self.creative_name,
            "object_story_spec": story_spec,
        })

    def _resolve_cta(self) -> str | None:
        """
        Return the Meta CTA enum string to use.

        Priority:
          1. Browser add-on CTA (Messenger / WhatsApp click)
          2. Explicit call_to_action field (already a Meta enum value)
          3. None
        """
        addon_cta = BROWSER_ADDON_CTA_MAP.get(self.browser_addons or "")
        if addon_cta:
            return addon_cta

        cta = (self.call_to_action or "").strip()
        # The Frappe select options are already Meta API strings (LEARN_MORE, etc.)
        return cta if cta and cta != "NO_BUTTON" else None

    def _get_file_meta(self, file_url: str) -> dict | None:
        """Resolve a Frappe File URL to useful metadata."""
        try:
            file_doc = frappe.get_doc("File", {"file_url": file_url})
            ext = (file_url or "").rsplit(".", 1)[-1].lower()
            return {
                "file_url":   file_url,
                "is_video":   ext in VIDEO_EXTENSIONS,
                "image_hash": getattr(file_doc, "image_hash", "") or "",
                "video_id":   getattr(file_doc, "video_id", "") or "",
            }
        except frappe.DoesNotExistError:
            logger.warning(f"File doc not found for URL: {file_url}")
            return None

    def _to_public_url(self, file_url: str) -> str:
        """
        Convert a Frappe-relative file URL to a fully-qualified, Meta-safe
        public URL.

        Why this is needed
        ------------------
        Meta's image URL validation is strict. URLs that work fine in browsers
        may be rejected by the Meta Marketing API with error 1885183.

        Fixes applied
        -------------
        1. Strips Frappe's version parameter (?v=TIMESTAMP).
           Frappe adds ?v=XXX for cache busting, but Meta rejects it.
           Input: /files/my-image.jpg?v=1703891234
           Output: /files/my-image.jpg

        2. Builds absolute URL from Frappe-relative paths.
           Input: /files/my-image.jpg
           Output: https://example.com/files/my-image.jpg

        3. Strips the port from ngrok / production URLs.
           Meta rejects non-standard ports (e.g. :8000) with subcode 3858258.
           Input: https://example.com:8000/files/image.jpg
           Output: https://example.com/files/image.jpg

        4. URL-encodes the filename path component.
           Spaces and special characters in filenames must be percent-encoded.
           Input: /files/College Ad.jpg
           Output: /files/College%20Ad.jpg

        5. Strips ALL query parameters and fragments.
           Meta REJECTS image URLs with any ?params or #anchors (error 1885183).
           Input: https://cdn.example.com/image.jpg?v=1&token=abc
           Output: https://cdn.example.com/image.jpg

        6. Validates URL is publicly accessible.
           Returns empty string for URLs Meta can never reach:
           - localhost / 127.0.0.1
           - Private network IPs (192.168.x.x, 10.x.x.x)
           - /private/files/ paths (require Frappe session auth)
        """
        if not file_url:
            return ""

        import urllib.parse as _up

        # STEP 1: Strip Frappe's ?v=TIMESTAMP parameter early
        # Frappe adds this for cache busting but Meta rejects it
        # Do this BEFORE building the absolute URL so we catch it
        if "?" in file_url:
            file_url = file_url.split("?")[0]
        if "#" in file_url:
            file_url = file_url.split("#")[0]

        # STEP 2: Build absolute URL from Frappe-relative path (/files/foo.jpg)
        if not file_url.startswith("http"):
            site_url = frappe.utils.get_url()
            file_url = f"{site_url.rstrip('/')}/{file_url.lstrip('/')}"

        # STEP 3: Parse URL to validate and clean it
        parsed = _up.urlparse(file_url)
        host = parsed.hostname or ""

        # STEP 4: Reject URLs that Meta cannot reach
        if (host in ("localhost", "127.0.0.1", "::1")
                or host.startswith("192.168.")
                or host.startswith("10.")):
            logger.warning(
                f"URL '{file_url}' is not publicly reachable by Meta (private network)."
            )
            return ""

        if "/private/files/" in file_url:
            logger.warning(f"Private file URL cannot be used with Meta: '{file_url}'")
            return ""

        # STEP 5: URL-encode the path (handles spaces and special chars)
        # quote() encodes everything except '/' so path structure is preserved
        encoded_path = _up.quote(parsed.path, safe="/:@!$&'()*+,;=")

        # STEP 6: Rebuild clean URL with NO query params or fragments
        # Meta strictly rejects any URL with ?parameters or #fragments
        clean_url = _up.urlunparse((
            parsed.scheme,
            host,            # hostname only — port intentionally dropped
            encoded_path,
            "",              # NO params
            "",              # NO query string (Meta rejects ?tracking=params)
            "",              # NO fragment (Meta rejects #anchors)
        ))

        if file_url != clean_url:
            logger.info(f"Cleaned picture URL: {file_url!r} → {clean_url!r}")
        else:
            logger.info(f"Picture URL (no cleaning needed): {clean_url!r}")
        
        return clean_url

    def _frappe_url_to_disk_path(self, file_url: str) -> str:
        """
        Resolve a Frappe file URL (relative or absolute) to the on-disk path
        so we can open the file and POST it to Meta's /adimages endpoint.

        Examples
        --------
        /private/files/foo.jpg  →  /home/frappe/frappe-bench/sites/mysite/private/files/foo.jpg
        /files/foo.jpg          →  /home/frappe/frappe-bench/sites/mysite/public/files/foo.jpg
        """
        if not file_url:
            return ""

        # Strip protocol + host if the URL is absolute
        from urllib.parse import urlparse as _urlparse
        path = _urlparse(file_url).path if file_url.startswith("http") else file_url

        site_path = frappe.utils.get_site_path()  # e.g. /bench/sites/mysite

        if path.startswith("/private/files/"):
            return site_path + path                # private/files lives inside site_path
        elif path.startswith("/files/"):
            return site_path + "/public" + path    # public files
        else:
            # Fallback: try site_path directly
            return site_path + path

    def _get_ad_label_ids(self) -> list:
        """Extract ad-label IDs from the ad_lables child table."""
        ids = []
        for row in (self.ad_lables or []):
            label_id = row.get("ad_label_id") or row.get("label_id") or row.get("name") or ""
            if label_id:
                ids.append(str(label_id).strip())
        return ids

    def _validate_url_accessible(self, url: str) -> bool:
        """
        Validate that the URL is actually accessible (optional check).
        
        This helps catch:
        - URLs that return 404
        - URLs that require authentication
        - URLs that are blocked by CORS/firewall
        - ngrok URLs that are rate-limited
        
        Returns True if accessible, False otherwise.
        """
        if not url or not url.startswith("http"):
            return False
        
        try:
            import requests
            
            # Log URL being tested
            logger.info(f"Testing URL accessibility: {url}")
            
            # Check if it's an ngrok URL - these need special attention
            is_ngrok = "ngrok" in url.lower()
            if is_ngrok:
                logger.warning(
                    "⚠️  NGROK URL detected - ngrok domains may be rate-limited or blocked "
                    "by external APIs like Meta. Consider using a real domain or IP whitelist."
                )
            
            # HEAD request is faster than GET, doesn't download the whole file
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.head(url, timeout=10, allow_redirects=True, headers=headers)
            is_accessible = response.status_code < 400
            
            if is_accessible:
                logger.info(f"✓ URL is accessible: {url} (status: {response.status_code})")
            else:
                logger.warning(
                    f"✗ URL returned error: {url} (status: {response.status_code})\n"
                    f"   Meta may not be able to download this image."
                )
            
            return is_accessible
        except requests.Timeout:
            logger.warning(f"✗ URL timeout (slow server or ngrok rate limit?): {url}")
            return False
        except requests.RequestException as e:
            logger.warning(f"✗ URL not accessible: {url} - {str(e)}")
            return False
        except Exception as e:
            logger.warning(f"✗ Error checking URL: {url} - {str(e)}")
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Standalone builder (callable from hooks / other modules / tests)
# ─────────────────────────────────────────────────────────────────────────────

def build_ad_creative_payload(doc) -> dict:
    """
    Convenience wrapper so external callers can obtain the payload without
    directly instantiating AdCreative.

    Usage::

        from frappe_social.ads_manager.doctype.ad_creative.ad_creative import (
            build_ad_creative_payload,
        )
        payload = build_ad_creative_payload(doc)
        result  = provider.create_creative(payload)
    """
    # ✅ CRITICAL FIX: AdCreative("Ad Creative") makes Frappe fetch a DB record
    # named "Ad Creative" which doesn't exist → "Ad Creative not found" error.
    # frappe.new_doc() correctly creates an in-memory document without a DB hit.
    creative = frappe.new_doc("Ad Creative")

    _FIELDS = [
        "creative_name", "select_facebook_page", "select_instagram_account",
        "select_threads_account", "select_ad_type", "selected_post_id",
        "format", "destination", "website_url", "display_link",
        "browser_addons", "medi", "media", "primary_text", "headline",
        "description", "call_to_action", "multi_advertiser_ads",
        "flexible_media", "add_music", "applink_treatment",
        "authorization_category", "branded_content_sponsor_page_id",
        "bundle_folder_id", "ad_lables",
    ]
    for field in _FIELDS:
        setattr(creative, field, getattr(doc, field, None))

    return creative.get_fb_payload()


# ─────────────────────────────────────────────────────────────────────────────
# Whitelisted API endpoints
# ─────────────────────────────────────────────────────────────────────────────

@frappe.whitelist()
def create_creative_on_meta(doc_name: str) -> dict:
    """
    Build the Meta payload for this Ad Creative and submit it to the
    Marketing API.  Saves the returned creative_id back to the document.

    Builds the Meta Marketing API payload from the Ad Creative document,
    submits it to ``POST /act_{id}/adcreatives``, and saves the returned
    ``creative_id`` back to the document.

    For single-image ads the image is passed as a ``picture`` URL.
    The URL must be publicly reachable by Meta's servers — localhost and
    Frappe ``/private/files/`` paths will be rejected early with a clear
    error message.

    Returns
    -------
    dict  { success: bool, creative_id?: str, error?: str }
    """
    doc = frappe.get_doc("Ad Creative", doc_name)

    if not doc.ad_account:
        frappe.throw(_("Please select an Ad Account before publishing"))

    from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider
    provider = MetaAdsProvider(integration_name=doc.ad_account)

    # Build payload
    payload = build_ad_creative_payload(doc)

    # ── Submit creative to Meta ───────────────────────────────────────────────
    result = provider.create_creative(payload)

    if result.success:
        doc.db_set("creative_id", result.creative_id, update_modified=False)
        frappe.db.commit()
        return {"success": True, "creative_id": result.creative_id}
    else:
        return {"success": False, "error": result.error_message}


@frappe.whitelist()
def get_facebook_pages(ad_account: str) -> list:
    """
    Retrieve Facebook pages linked to the chosen Ads Account Integration.

    Returns
    -------
    list[dict]  Each item has ``page_id`` and ``page_name``.
    """
    if not ad_account:
        return []
    try:
        integration = frappe.get_doc("Ads Account Integration", ad_account)
        pages = []
        for asset in (integration.meta_assets or []):
            if asset.get("platform") == "Facebook":
                pages.append({
                    "page_id":   asset.get("page_id", ""),
                    "page_name": asset.get("page_name", ""),
                    "platform":  "Facebook",
                })
        logger.info(f"Retrieved {len(pages)} Facebook pages for {ad_account}")
        return pages
    except frappe.DoesNotExistError:
        frappe.throw(_("Ad account not found: {0}").format(ad_account))
    except Exception as e:
        logger.error(f"Error retrieving Facebook pages: {e}")
        frappe.throw(_("Error retrieving Facebook pages: {0}").format(str(e)))


@frappe.whitelist()
def get_instagram_account(ad_account: str) -> list:
    """
    Retrieve Instagram accounts linked to the chosen Ads Account Integration.

    Returns
    -------
    list[dict]  Each item has ``page_id`` (IG actor ID) and ``page_name``
                (Instagram username).
    """
    if not ad_account:
        return []
    try:
        integration = frappe.get_doc("Ads Account Integration", ad_account)
        accounts = []
        for asset in (integration.meta_assets or []):
            if asset.get("platform") == "Instagram":
                accounts.append({
                    "page_id":   asset.get("page_id", ""),
                    "page_name": asset.get("username", ""),
                    "platform":  "Instagram",
                })
        logger.info(f"Retrieved {len(accounts)} Instagram accounts for {ad_account}")
        return accounts
    except frappe.DoesNotExistError:
        frappe.throw(_("Ad account not found: {0}").format(ad_account))
    except Exception as e:
        logger.error(f"Error retrieving Instagram accounts: {e}")
        frappe.throw(_("Error retrieving Instagram accounts: {0}").format(str(e)))


@frappe.whitelist()
def get_existing_posts(ad_account: str, page_id: str, limit: int = 50) -> list:
    """
    Fetch existing posts from a Facebook Page for use as ad creatives.

    Parameters
    ----------
    ad_account : Frappe name of the Ads Account Integration document
    page_id    : Facebook Page numeric ID
    limit      : Max posts to fetch (default 50)

    Returns
    -------
    list[dict]  Post objects with keys:
                post_id, message, media_url, source, media_type,
                created_date, permalink
    """
    import requests
    from datetime import datetime

    if not ad_account or not page_id:
        return []

    try:
        integration = frappe.get_doc("Ads Account Integration", ad_account)

        # Find the Page access token for this page
        page_access_token = None
        for asset in (integration.meta_assets or []):
            if asset.get("platform") == "Facebook" and asset.get("page_id") == page_id:
                page_access_token = asset.get("page_access_token")
                break

        if not page_access_token:
            # Fall back to account access token
            page_access_token = integration.get_access_token()

        if not page_access_token:
            frappe.throw(_(
                "No access token found for page {0}. "
                "Please reconnect the ad account."
            ).format(page_id))

        settings = frappe.get_single("Social Settings")
        api_version = settings.meta_api_version or "v25.0"

        url = f"https://graph.facebook.com/{api_version}/{page_id}/posts"
        params = {
            "access_token": page_access_token,
            "fields":       "id,message,story,created_time,type,picture,permalink_url,status_type",
            "limit":        int(limit),
        }

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            err = data["error"]
            frappe.throw(_(
                "Meta API error fetching posts: [{0}] {1}"
            ).format(err.get("code"), err.get("message")))

        posts = []
        for post in data.get("data", []):
            text = post.get("message") or post.get("story") or ""
            if not text:
                continue  # skip blank / system posts

            posts.append({
                "post_id":      post.get("id", ""),
                "message":      text,
                "media_url":    post.get("picture", ""),
                "source":       (post.get("status_type") or "feed").replace("_", " ").title(),
                "media_type":   (post.get("type") or "status").title(),
                "created_date": _parse_date(post.get("created_time", "")),
                "permalink":    post.get("permalink_url", ""),
            })

        logger.info(f"Retrieved {len(posts)} posts from Facebook page {page_id}")
        return posts

    except requests.RequestException as e:
        logger.error(f"Network error fetching posts: {e}")
        frappe.throw(_("Failed to fetch posts from Facebook. Check your connection."))
    except frappe.DoesNotExistError:
        frappe.throw(_("Ad account not found: {0}").format(ad_account))
    except Exception as e:
        logger.error(f"Error retrieving posts: {e}")
        frappe.throw(_("Error retrieving posts: {0}").format(str(e)))


@frappe.whitelist()
def test_image_url(file_url: str) -> dict:
    """
    Test if Meta can download an image from the given URL.
    
    This is more rigorous than debug_file_url - it actually tries to:
    1. Download the image
    2. Check file size
    3. Verify it's a valid image
    4. Simulate what Meta's servers will do
    
    Usage:
        frappe.call({
            method: 'frappe_social.ads_manager.doctype.ad_creative.ad_creative.test_image_url',
            args: { file_url: 'https://example.com/image.jpg' },
            callback: r => console.log(r.message)
        })
    
    Returns:
        success: True if Meta can access it, False otherwise
        details: Information about the URL and access test
        warnings: List of warnings/issues found
        error: Error message if failed
    """
    if not file_url:
        return {"error": "file_url is required"}
    
    try:
        import requests
        from io import BytesIO
        from PIL import Image
        
        logger.info(f"\n{'='*70}")
        logger.info(f"DETAILED IMAGE URL TEST")
        logger.info(f"{'='*70}")
        logger.info(f"URL: {file_url}\n")
        
        warnings = []
        
        # Check for ngrok
        if "ngrok" in file_url.lower():
            warnings.append(
                "Using ngrok domain - these are often blocked by production APIs like Meta. "
                "This is OK for development but will fail with real creatives."
            )
        
        # Test HEAD request (fast, no download)
        logger.info(f"[1/4] Testing HEAD request...")
        headers = {"User-Agent": "Mozilla/5.0"}
        head_response = requests.head(file_url, timeout=10, allow_redirects=True, headers=headers)
        logger.info(f"      Status: {head_response.status_code}")
        
        if head_response.status_code >= 400:
            return {
                "success": False,
                "error": f"URL returned HTTP {head_response.status_code}",
                "details": {
                    "url": file_url,
                    "status": head_response.status_code,
                    "accessible": False
                },
                "warnings": warnings
            }
        
        # Test GET request (actually download)
        logger.info(f"[2/4] Downloading image...")
        get_response = requests.get(file_url, timeout=10, headers=headers)
        file_size = len(get_response.content)
        logger.info(f"      Size: {file_size} bytes (~{file_size/1024/1024:.2f} MB)")
        
        # Meta image size limits
        if file_size == 0:
            return {
                "success": False,
                "error": "Image file is empty (0 bytes)",
                "details": {"url": file_url, "size": 0, "accessible": True},
                "warnings": warnings
            }
        
        if file_size > 4 * 1024 * 1024:  # 4MB
            warnings.append(f"Image is {file_size/1024/1024:.2f} MB - Max is 4MB for Meta")
        
        # Check Content-Type
        content_type = get_response.headers.get("Content-Type", "unknown")
        logger.info(f"[3/4] Content-Type: {content_type}")
        
        valid_types = ["image/jpeg", "image/png", "image/gif", "image/webp"]
        if not any(vt in content_type.lower() for vt in valid_types):
            warnings.append(f"Content-Type '{content_type}' may not be valid for Meta images")
        
        # Try to parse as image
        logger.info(f"[4/4] Validating image file...")
        try:
            img = Image.open(BytesIO(get_response.content))
            logger.info(f"      Image format: {img.format}, Size: {img.size}px, Mode: {img.mode}")
            image_info = {
                "format": img.format,
                "dimensions": img.size,
                "mode": img.mode
            }
        except Exception as e:
            warnings.append(f"File may not be a valid image: {str(e)}")
            image_info = None
        
        logger.info(f"\n{'='*70}")
        logger.info(f"RESULT: ✓ URL is accessible and appears to be a valid image")
        logger.info(f"{'='*70}\n")
        
        return {
            "success": True,
            "details": {
                "url": file_url,
                "status": get_response.status_code,
                "accessible": True,
                "size_bytes": file_size,
                "size_mb": round(file_size / 1024 / 1024, 2),
                "content_type": content_type,
                "image": image_info
            },
            "warnings": warnings if warnings else None,
            "message": "Image looks good! Try creating the creative now."
        }
    
    except requests.Timeout:
        return {
            "success": False,
            "error": "Request timeout - URL is too slow or unreachable (ngrok rate limit?)",
            "details": {"url": file_url},
            "warnings": warnings
        }
    except requests.RequestException as e:
        return {
            "success": False,
            "error": f"Network error: {str(e)}",
            "details": {"url": file_url},
            "warnings": warnings
        }
    except Exception as e:
        logger.error(f"Test error: {str(e)}\n{frappe.get_traceback()}")
        return {
            "success": False,
            "error": str(e),
            "details": {"url": file_url}
        }



# ─────────────────────────────────────────────────────────────────────────────
# Internal utilities
# ─────────────────────────────────────────────────────────────────────────────

def _parse_date(date_string: str) -> str:
    """Parse ISO-8601 date string from Meta API into a human-readable format."""
    if not date_string:
        return ""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(date_string.replace("Z", "+00:00"))
        return dt.strftime("%d %b %Y")
    except Exception:
        return date_string