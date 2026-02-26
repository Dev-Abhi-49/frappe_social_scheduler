import frappe
from frappe.model.document import Document
from frappe import _
from frappe_social.frappe_social.utils.media import normalize_file_type
import os
import json
import re
import html
from typing import Dict, Optional


class PostAds(Document):
    """
    Post Ads - Pure Meta Ads Manager
    Handles: Campaign → Ad Set → Creative → Ad
    """

    VALID_TRANSITIONS = {
        "Draft": ["Publishing", "Cancelled"],
        "Publishing": ["Published", "Failed"],
        "Published": [],
        "Failed": ["Publishing"],
        "Cancelled": ["Draft"],
    }

    def before_save(self):
        """Auto-set defaults for ads"""
        if not self.status:
            self.status = "Draft"

    def validate(self):
        """Ad-only validation"""
        self.fix_media_metadata()
        self.validate_ad_fields()
        if self.media:
            self.validate_media()
        if self.content:
            self.validate_content_length()

    def validate_ad_fields(self):
        """Required fields for Meta Ad creation"""
        required = {
            'campaign': 'Campaign',
            'select_ad_account': 'Ads Account Integration',
            'select_ad_set': 'Ad Set',
            'selected_facebook_page': 'Facebook Page'
        }

        for field, label in required.items():
            if not self.get(field):
                frappe.throw(
                    _(f"{label} is required for ad creation"),
                    title=_("Missing Field")
                )

        # Campaign must be Meta
        campaign = frappe.get_doc('Marketing Campaign', self.campagin)
        if not campaign.custom_is_meta_ads:
            frappe.throw(_("Campaign must be Meta Ads"), title=_("Invalid Campaign"))

        # Account connected?
        ad_account = frappe.get_doc('Ads Account Integration', self.select_ad_account)
        if ad_account.connection_status != 'Connected':
            frappe.throw(_("Ad account not connected"), title=_("Connection Error"))

        # Ad Set valid?
        ad_set = frappe.get_doc('Ad Set', self.select_ad_set)
        if ad_set.campaign != self.campagin or not ad_set.adset_id:
            frappe.throw(_("Ad Set invalid or not created on Meta"), title=_("Invalid Ad Set"))

    def fix_media_metadata(self):
        """Fix file metadata"""
        if not self.media:
            return
        for item in self.media:
            if not item.file:
                continue
            try:
                db_file = frappe.db.get_value(
                    "File", {"file_url": item.file}, ["file_type", "file_size"], as_dict=True
                )
                if db_file:
                    item.file_size = db_file.get('file_size') or 0
                    item.file_type = normalize_file_type(item.file, db_file.get('file_type'))
            except Exception as e:
                frappe.log_error(f"Media metadata error: {str(e)}", "Post Ads")

    def validate_content_length(self):
        """Basic content check"""
        if len(self.content or "") > 63206:  # Facebook max
            frappe.throw(_("Content too long for Meta Ads"), title=_("Content Error"))

    def validate_media(self):
        """Media for Meta Ads"""
        if len(self.media) > 10:
            frappe.throw(_("Max 10 media files for ads"), title=_("Media Limit"))
        for media in self.media:
            file_type = (media.file_type or "").lower()
            if not ("image" in file_type or "video" in file_type):
                frappe.throw(_("Only images/videos allowed"), title=_("Invalid Media"))

    # =====================================================
    # AD CREATIVE & PUBLISHING
    # =====================================================

    def build_ad_creative_payload(self) -> Dict:
        """Build clean Meta Creative payload (image_hash)"""
        page_id = self._get_facebook_page_id()
        creative_name = self.ad_name or f"Creative-{self.name}"
        link_url = self.ad_creative[0].link_url if self.ad_creative else ""
        
        link_data = {
            "link": link_url or "https://walue.biz",
            "description": (self.content or "Ad")[:200],
            "caption": link_url.split('//')[-1].split('/')[0] if link_url else "walue.biz"
        }

        # CTA
        if self.ad_creative and self.ad_creative[0].call_to_action:
            cta = self._map_cta_to_meta_format(self.ad_creative[0].call_to_action)
            link_data["call_to_action"] = {"type": cta}

        # Media (image_hash)
        if self.media:
            if len(self.media) == 1:
                image_hash = self._upload_image_to_meta(self.media[0].file)
                if image_hash:
                    link_data["image_hash"] = image_hash
            else:
                child_attachments = []
                for m in self.media:
                    h = self._upload_image_to_meta(m.file)
                    if h:
                        child_attachments.append({"image_hash": h, "link": link_url})
                if child_attachments:
                    link_data["child_attachments"] = child_attachments

        creative_payload = {
            "name": creative_name,
            "object_story_spec": {
                "page_id": page_id,
                "link_data": link_data
            }
        }

        frappe.log_error(json.dumps(creative_payload, indent=2), f"Creative Payload - {self.name}")
        return creative_payload

    def build_ad_payload(self, creative_id: str) -> Dict:
        """Build Meta Ad payload"""
        ad_set = frappe.get_doc('Ad Set', self.select_ad_set)
        ad_name = self.ad_name or f"Ad-{self.name}"
        
        return {
            "name": ad_name,
            "adset_id": ad_set.adset_id,
            "creative": {"creative_id": creative_id},
            "status": "PAUSED"
        }

    def _get_facebook_page_id(self) -> str:
        """Get page ID from account"""
        ad_account = frappe.get_doc('Ads Account Integration', self.select_ad_account)
        for page in ad_account.fb_pages:
            if page.page_name == self.selected_facebook_page:
                return page.page_id
        frappe.throw(_("Page not found"), title=_("Page Error"))

    def _upload_image_to_meta(self, file_url: str) -> Optional[str]:
        """Upload & return image_hash"""
        try:
            from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider
            file_path = frappe.get_site_path('public', file_url.lstrip('/'))
            if not os.path.exists(file_path):
                return None
            provider = MetaAdsProvider(self.select_ad_account)
            result = provider.upload_image({"filename": file_path})
            return result.image_hash if result.success else None
        except Exception as e:
            frappe.log_error(str(e), "Image Upload")
            return None

    def _map_cta_to_meta_format(self, cta: str) -> str:
        mapping = {
            "Learn More": "LEARN_MORE",
            "Shop Now": "SHOP_NOW",
            "Sign Up": "SIGN_UP"
        }
        return mapping.get(cta, "LEARN_MORE")

    def publish_as_ad(self):
        """Publish Ad (Creative → Ad)"""
        try:
            from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider

            self.status = "Publishing"
            self.save(ignore_permissions=True)

            provider = MetaAdsProvider(self.select_ad_account)

            # Create Creative
            creative_payload = self.build_ad_creative_payload()
            creative_result = provider.create_creative(creative_payload)
            if not creative_result.success:
                raise Exception(creative_result.error_message)
            creative_id = creative_result.creative_id

            # Update child table
            if self.ad_creative:
                frappe.db.set_value("Ad Creative", self.ad_creative[0].name, "creative_id", creative_id)

            # Create Ad
            ad_payload = self.build_ad_payload(creative_id)
            ad_result = provider.create_ad(ad_payload)
            if not ad_result.success:
                raise Exception(ad_result.error_message)

            # Success
            self.ad_id = ad_result.ad_id
            self.status = "Published"
            self.save(ignore_permissions=True)

            return {"success": True, "ad_id": self.ad_id}

        except Exception as e:
            self.status = "Failed"
            self.error_log = str(e)
            self.save(ignore_permissions=True)
            frappe.log_error(frappe.get_traceback(), f"Ad Publish Failed - {self.name}")
            return {"success": False, "error_message": str(e)}


# =====================================================
# WHITELISTED FUNCTIONS
# =====================================================

@frappe.whitelist()
def publish_ad(post_name):
    """Publish Post Ads"""
    try:
        doc = frappe.get_doc("Post Ads", post_name)
        result = doc.publish_as_ad()
        return result
    except Exception as e: 
        frappe.log_error(str(e), f"Publish Ad Error - {post_name}")
        return {"success": False, "error_message": str(e)}

@frappe.whitelist()
def get_platforms_for_organization(organization):
    """Get available platforms for an organization"""
    if not organization:
        return []

    return frappe.db.get_all(
        "Ads Account Integration",
        filters={"organization": organization, "enabled": 1, "connection_status": "Connected"},
        pluck="platform",
        distinct=True,
        order_by="platform asc",
    )

@frappe.whitelist()
def get_campaigns_for_account(ad_account):
    """Get campaigns for account (for form)"""
    if not ad_account:
        return []
    
    return frappe.db.get_all(
        "Marketing Campaign",
        filters={"custom_select_facebook_ad_account": ad_account, "custom_is_meta_ads": 1},
        pluck="name",
        distinct=True,
        order_by="name asc",
    )