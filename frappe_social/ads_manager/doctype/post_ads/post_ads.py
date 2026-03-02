"""
Post Ads - Meta Ad Manager
Manages ad creation and publishing to Meta (Facebook/Instagram)
"""

import frappe
from frappe.model.document import Document
from frappe import _
from datetime import datetime
from typing import Dict, Optional


class PostAds(Document):
    """
    Post Ads DocType
    
    Fields:
    - enable_ad: Enable/disable the ad (Check)
    - ad_name: Name of the ad (Data, required)
    - campaign: Marketing campaign link (Link, required)
    - status: Ad status - ACTIVE, PAUSED, DELETED, ARCHIVED (Select, read-only)
    - partnership_ad: Whether this is a partnership ad (Check)
    - select_ad_set: Ad set for the ad (Link, required)
    - schedule_time: When to schedule the ad (Datetime)
    - id: External Meta ad ID (Data)
    - select_ad_creative: Ad creative to use (Link)
    """

    def before_save(self):
        """Auto-set defaults before saving"""
        if not self.status:
            self.status = "PAUSED"
        
        if not self.enable_ad:
            self.enable_ad = 0
        
        if not self.partnership_ad:
            self.partnership_ad = 0

    def validate(self):
        """Validate ad fields"""
        self.validate_required_fields()
        self.validate_campaign()
        self.validate_ad_set()
        self.validate_creative()
        self.validate_schedule_time()

    def validate_required_fields(self):
        """Check required fields are filled"""
        required_fields = {
            'ad_name': _('Ad Name'),
            'campaign': _('Campaign'),
            'select_ad_set': _('Ad Set'),
            'select_ad_creative': _('Ad Creative')
        }

        for field, label in required_fields.items():
            if not self.get(field):
                frappe.throw(
                    _("{0} is required").format(label),
                    title=_("Validation Error")
                )

    def validate_campaign(self):
        """Validate campaign exists and is Meta Ads enabled"""
        try:
            campaign = frappe.get_doc('Marketing Campaign', self.campaign)
            
            # Check if it's a Meta campaign (if that field exists)
            if hasattr(campaign, 'custom_is_meta_ads'):
                if not campaign.custom_is_meta_ads:
                    frappe.throw(
                        _("Campaign must be enabled for Meta Ads"),
                        title=_("Invalid Campaign")
                    )
        except frappe.DoesNotExistError:
            frappe.throw(
                _("Campaign {0} does not exist").format(self.campaign),
                title=_("Campaign Error")
            )

    def validate_ad_set(self):
        """Validate ad set is valid and belongs to campaign"""
        try:
            ad_set = frappe.get_doc('Ad Set', self.select_ad_set)
            
            # Check ad set belongs to this campaign
            if ad_set.campaign != self.campaign:
                frappe.throw(
                    _("Ad Set {0} does not belong to Campaign {1}").format(
                        self.select_ad_set, self.campaign
                    ),
                    title=_("Invalid Ad Set")
                )
            
            # Check ad set is created on Meta
            if not ad_set.adset_id:
                frappe.throw(
                    _("Ad Set {0} has not been created on Meta yet").format(
                        self.select_ad_set
                    ),
                    title=_("Ad Set Not Active")
                )
        except frappe.DoesNotExistError:
            frappe.throw(
                _("Ad Set {0} does not exist").format(self.select_ad_set),
                title=_("Ad Set Error")
            )

    def validate_creative(self):
        """Validate ad creative exists"""
        try:
            creative = frappe.get_doc('Ad Creative', self.select_ad_creative)
            
            # Check creative is valid
            if not creative.creative_id:
                frappe.throw(
                    _("Ad Creative {0} has not been created on Meta yet").format(
                        self.select_ad_creative
                    ),
                    title=_("Creative Not Active")
                )
        except frappe.DoesNotExistError:
            frappe.throw(
                _("Ad Creative {0} does not exist").format(self.select_ad_creative),
                title=_("Creative Error")
            )

    def validate_schedule_time(self):
        """Validate schedule time is in the future if set"""
        if self.schedule_time:
            scheduled = datetime.fromisoformat(str(self.schedule_time))
            now = datetime.now()
            
            if scheduled < now:
                frappe.throw(
                    _("Schedule time must be in the future"),
                    title=_("Invalid Schedule Time")
                )

    # =====================================================
    # AD PUBLISHING METHODS
    # =====================================================

    def publish_ad(self):
        """
        Publish ad to Meta
        Status flow: PAUSED → publish to Meta with ID
        """
        if not self.enable_ad:
            frappe.throw(
                _("Please enable the ad before publishing"),
                title=_("Ad Not Enabled")
            )
        
        try:
            from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider
            
            # Get ad set details
            ad_set = frappe.get_doc('Ad Set', self.select_ad_set)
            creative = frappe.get_doc('Ad Creative', self.select_ad_creative)
            
            # Initialize Meta provider
            account_integration = self.get_account_integration()
            provider = MetaAdsProvider(account_integration)
            
            # Build ad payload
            ad_payload = {
                "name": self.ad_name,
                "adset_id": ad_set.adset_id,
                "creative": {"creative_id": creative.creative_id},
                "status": "PAUSED"  # Always start paused
            }
            
            # Create ad on Meta
            result = provider.create_ad(ad_payload)
            
            if not result.success:
                frappe.throw(
                    _("Failed to create ad on Meta: {0}").format(result.error_message),
                    title=_("Meta API Error")
                )
            
            # Store the Meta ad ID
            self.id = result.ad_id
            self.status = "ACTIVE"
            self.save(ignore_permissions=True)
            
            return {
                "success": True,
                "message": _("Ad published successfully"),
                "ad_id": result.ad_id
            }
            
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Post Ads - Publish Error")
            return {
                "success": False,
                "message": str(e)
            }

    def pause_ad(self):
        """Pause the ad on Meta"""
        if not self.id:
            frappe.throw(_("No Meta ad ID found"), title=_("Ad Not Published"))
        
        try:
            from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider
            
            account_integration = self.get_account_integration()
            provider = MetaAdsProvider(account_integration)
            
            # Update ad status to PAUSED
            result = provider._make_request(
                "POST",
                f"{self.id}",
                json_data={"status": "PAUSED"}
            )
            
            self.status = "PAUSED"
            self.save(ignore_permissions=True)
            
            return {"success": True, "message": _("Ad paused")}
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Post Ads - Pause Error")
            return {"success": False, "message": str(e)}

    def resume_ad(self):
        """Resume the ad on Meta"""
        if not self.id:
            frappe.throw(_("No Meta ad ID found"), title=_("Ad Not Published"))
        
        try:
            from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider
            
            account_integration = self.get_account_integration()
            provider = MetaAdsProvider(account_integration)
            
            # Update ad status to ACTIVE
            result = provider._make_request(
                "POST",
                f"{self.id}",
                json_data={"status": "ACTIVE"}
            )
            
            self.status = "ACTIVE"
            self.save(ignore_permissions=True)
            
            return {"success": True, "message": _("Ad resumed")}
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Post Ads - Resume Error")
            return {"success": False, "message": str(e)}

    def get_analytics(self):
        """Get ad performance analytics"""
        if not self.id:
            return {
                "success": False,
                "message": _("Ad not published yet")
            }
        
        try:
            from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider
            
            account_integration = self.get_account_integration()
            provider = MetaAdsProvider(account_integration)
            
            # Fetch ad analytics
            result = provider.fetch_ad_analytics(self.id)
            
            if result.success:
                return {
                    "success": True,
                    "metrics": result.metrics
                }
            else:
                return {
                    "success": False,
                    "message": result.error_message
                }
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Post Ads - Analytics Error")
            return {
                "success": False,
                "message": str(e)
            }

    # =====================================================
    # HELPER METHODS
    # =====================================================

    def get_account_integration(self) -> str:
        """
        Get the account integration name from the ad set
        This is needed to initialize the Meta provider
        """
        ad_set = frappe.get_doc('Ad Set', self.select_ad_set)
        if hasattr(ad_set, 'account_integration'):
            return ad_set.account_integration
        
        # Fallback: try to get from campaign
        campaign = frappe.get_doc('Marketing Campaign', self.campaign)
        if hasattr(campaign, 'custom_select_facebook_ad_account'):
            return campaign.custom_select_facebook_ad_account
        
        frappe.throw(
            _("Could not find Account Integration"),
            title=_("Configuration Error")
        )


# =====================================================
# WHITELISTED FUNCTIONS
# =====================================================

@frappe.whitelist()
def publish_ad(post_ads_name):
    """Publish an ad to Meta"""
    try:
        doc = frappe.get_doc("Post Ads", post_ads_name)
        return doc.publish_ad()
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Post Ads - Publish Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def pause_ad(post_ads_name):
    """Pause an ad on Meta"""
    try:
        doc = frappe.get_doc("Post Ads", post_ads_name)
        return doc.pause_ad()
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Post Ads - Pause Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def resume_ad(post_ads_name):
    """Resume an ad on Meta"""
    try:
        doc = frappe.get_doc("Post Ads", post_ads_name)
        return doc.resume_ad()
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Post Ads - Resume Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def get_ad_analytics(post_ads_name):
    """Get analytics for an ad"""
    try:
        doc = frappe.get_doc("Post Ads", post_ads_name)
        return doc.get_analytics()
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Post Ads - Analytics Error")
        return {"success": False, "message": str(e)}


@frappe.whitelist()
def get_campaigns_for_campaign_type(campaign_type="Meta Ads"):
    """Get available campaigns"""
    if not campaign_type:
        return []
    
    return frappe.db.get_all(
        "Marketing Campaign",
        filters={"custom_is_meta_ads": 1, "docstatus": 0},
        fields=["name", "title"],
        order_by="name asc"
    )


@frappe.whitelist()
def get_ad_sets_for_campaign(campaign):
    """Get ad sets for a campaign"""
    if not campaign:
        return []
    
    return frappe.db.get_all(
        "Ad Set",
        filters={"campaign": campaign},
        fields=["name", "title"],
        order_by="name asc"
    )


@frappe.whitelist()
def get_creatives_for_ad_set(ad_set):
    """Get creatives for an ad set"""
    if not ad_set:
        return []
    
    return frappe.db.get_all(
        "Ad Creative",
        filters={"docstatus": 0},
        fields=["name", "title"],
        order_by="name asc"
    )