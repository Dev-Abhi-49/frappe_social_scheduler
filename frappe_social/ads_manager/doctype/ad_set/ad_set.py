import frappe
import logging
import json
from frappe import _
from frappe.model.document import Document
from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider

logger = logging.getLogger(__name__)


class AdSet(Document):

    def before_save(self):
        """Validate required fields before saving to Frappe"""
        # Just validate, don't create on Meta automatically
        # Meta creation happens when user clicks "Create on Meta" button
        
        if not self.ad_set_name:
            frappe.throw(_("Ad Set Name is required"))
        
        if not self.campaign:
            frappe.throw(_("Campaign is required"))
        
        if not self.billing_event:
            frappe.throw(_("Billing Event is required"))
        
        if not self.performance_goal:
            frappe.throw(_("Optimization Goal is required"))
        
        # if not self.budget_type_dailylifetime:
        #     frappe.throw(_("Budget Type is required"))
        
        # Validate budget only if campaign doesn't have CBO
        campaign_doc = frappe.get_doc("Marketing Campaign", self.campaign)
        has_cbo = getattr(campaign_doc, 'custom_enable_adset_budget_sharing', False)
        
        if not has_cbo and (not self.amount or self.amount <= 0):
            frappe.throw(_("Ad Set Amount is required and must be greater than 0 (Campaign Budget Optimization is disabled)"))

    def _create_meta_ad_set(self):
        """Actual creation logic"""
        try:
            if not self.ad_set_name:
                frappe.throw(_("Ad Set Name is required"))
            
            # Fetch campaign document
            if not self.campaign:
                frappe.throw(_("Campaign is required"))
            if not self.billing_event:
                frappe.throw(_("Billing Event is required"))
            
            campaign_doc = frappe.get_doc("Marketing Campaign", self.campaign)

            if not campaign_doc.custom_facebook_campaign_id:
                frappe.throw(_("Campaign has no Facebook Campaign ID. Please create the campaign on Meta first."))
            if not campaign_doc.custom_select_facebook_ad_account:
                frappe.throw(_("Campaign has no Facebook Ad Account configured"))

            # ─── Budget Validation ────────────────────────────────────────
            has_cbo = getattr(campaign_doc, 'custom_enable_adset_budget_sharing', False)
            if not has_cbo and not self.amount:
                frappe.throw(_("Ad Set Budget (Amount) is required when Campaign Budget Optimization is NOT enabled"))

            provider = MetaAdsProvider(campaign_doc.custom_select_facebook_ad_account)
            payload = self._build_ad_set_payload(campaign_doc)

            logger.info(f"Creating Ad Set '{self.ad_set_name}' on Meta")
            logger.debug(f"Payload: {json.dumps(payload, indent=2, default=str)}")

            result = provider.create_ad_set(payload)

            if result.success:
                self.adset_id = result.adset_id or getattr(result, 'campaign_id', None)
                frappe.msgprint(f"✅ SUCCESS! Ad Set created on Meta.<br><b>ID: {self.adset_id}</b>", 
                               alert=True, indicator="green")
                logger.info(f"Ad Set saved with ID: {self.adset_id}")
            else:
                error = result.error_message or "Unknown Meta error"
                frappe.msgprint(f"❌ Meta creation FAILED: {error}", alert=True, indicator="red")
                frappe.throw(f"Failed to create on Meta: {error}")

        except Exception as e:
            frappe.msgprint(f"💥 EXCEPTION during creation: {str(e)}", alert=True, indicator="red")
            logger.error(f"Ad Set error: {str(e)}")
            frappe.log_error(frappe.get_traceback(), "Ad Set Meta Creation Error")
            raise

    # ====================== PAYLOAD BUILDER ======================
    def _build_ad_set_payload(self, campaign_doc) -> dict:
        """
        Build Ad Set payload for Meta API
        
        Budget Handling:
        - If Campaign has CBO enabled (custom_enable_adset_budget_sharing=True):
          → Budget is set at campaign level, do NOT include budget in ad set
        - If Campaign has CBO disabled (custom_enable_adset_budget_sharing=False):
          → Budget MUST be set at ad set level, include budget fields
        
        Reference: https://developers.facebook.com/docs/marketing-api/reference/ad-account/campaigns/v25.0
        """

        payload = {
            "name": self.ad_set_name,
            "campaign_id": campaign_doc.custom_facebook_campaign_id,
            "billing_event": self.billing_event,
            "optimization_goal": self.performance_goal,
            "status": "ACTIVE" if self.enable_ad_set else "PAUSED",
        }

        # ─── Budget Handling ──────────────────────────────────────────────
        # Check if campaign has CBO (Campaign Budget Optimization) enabled
        has_cbo = getattr(campaign_doc, 'custom_enable_adset_budget_sharing', False)
        
        if not has_cbo:
            # Budget must be at ad set level (ABrO - Ad Set Budget Rules Only)
            if not self.amount:
                frappe.throw(_("Ad Set Amount is required when Campaign Budget Optimization is disabled"))
            
            amount_float = float(self.amount)
            budget_minor = int(amount_float * 100)
            
            if self.budget_type_dailylifetime == "Lifetime Budget":
                payload["lifetime_budget"] = budget_minor
            else:
                payload["daily_budget"] = budget_minor
        else:
            # Budget is at campaign level, do NOT include in ad set
            logger.info(f"Campaign has CBO enabled - skipping Ad Set budget fields")

        # ─── Optional Fields ──────────────────────────────────────────────
        if self.bid_amount:
            payload["bid_amount"] = int(float(self.bid_amount) * 100)
        if self.bid_strategy:
            payload["bid_strategy"] = self.bid_strategy
        if self.start_date_and_time:
            payload["start_time"] = self._to_unix_timestamp(self.start_date_and_time)
        if self.end_date_and_time:
            payload["end_time"] = self._to_unix_timestamp(self.end_date_and_time)
        if self.destination_type:
            payload["destination_type"] = self.destination_type
        if self.is_dynamic_creative:
            payload["is_dynamic_creative"] = True

        targeting = self._build_targeting()
        if targeting:
            payload["targeting"] = targeting

        return payload

    def _build_targeting(self) -> dict:
        targeting = {}
        
        # ─── Age Targeting ────────────────────────────────────────────────
        if self.age_min or self.age_max:
            targeting["age_min"] = int(self.age_min or 18)
            targeting["age_max"] = int(self.age_max or 65)

        # ─── Gender Targeting ────────────────────────────────────────────
        if self.gender and self.gender != "All":
            gender_map = {"Male": 1, "Female": 2}
            targeting["genders"] = [gender_map[self.gender]]

        # ─── Country/Geo Targeting (from 'country' table field) ──────────
        if self.country:
            countries = []
            for row in self.country:
                # Each row has country data, get the country code
                if hasattr(row, 'country') and row.country:
                    try:
                        country_doc = frappe.get_doc("Country", row.country)
                        countries.append(country_doc.code or row.country)
                    except:
                        countries.append(row.country)
            
            if countries:
                targeting["geo_locations"] = {"countries": countries}

        # ─── Language Targeting (from 'language' table field) ────────────
        if self.language:
            locales = []
            for row in self.language:
                # Each row has language data, get the language code
                if hasattr(row, 'language') and row.language:
                    try:
                        lang_doc = frappe.get_doc("Language", row.language)
                        locales.append(lang_doc.language_code or row.language)
                    except:
                        locales.append(row.language)
            
            if locales:
                targeting["locales"] = locales

        # ─── Device Platform Targeting ────────────────────────────────
        if self.device_platforms and self.device_platforms != "All Devices":
            device_map = {"Mobile": ["mobile"], "Desktop": ["desktop"]}
            targeting["device_platforms"] = device_map.get(self.device_platforms, ["mobile", "desktop"])
            targeting["publisher_platforms"] = ["facebook", "audience_network"]

        return targeting

    def _to_unix_timestamp(self, dt_value) -> int:
        import datetime
        from dateutil import parser
        if isinstance(dt_value, datetime.datetime):
            return int(dt_value.timestamp())
        if isinstance(dt_value, datetime.date):
            return int(datetime.datetime.combine(dt_value, datetime.time()).timestamp())
        try:
            return int(parser.parse(str(dt_value)).timestamp())
        except:
            return int(datetime.datetime.now().timestamp())

    @frappe.whitelist()
    def create_meta_ad_set(self):
        """Whitelisted method to create ad set on Meta"""
        if self.adset_id:
            return {"success": False, "message": "Ad Set already created (ID exists)"}
        
        try:
            self._create_meta_ad_set()
            return {"success": True, "adset_id": self.adset_id, "message": "Ad Set created successfully"}
        except Exception as e:
            logger.error(f"Failed to create ad set: {str(e)}")
            return {"success": False, "message": str(e)}


# ═════════════════════════════════════════════════════════════════════════════
# WHITELISTED API ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def create_ad_set_on_meta_async(ad_set_name: str) -> dict:
    """
    Create Ad Set on Meta (async endpoint called from button click)
    
    Reference: https://developers.facebook.com/docs/marketing-api/reference/ad-account/adsets/v25.0
    
    REQUIRED FIELDS for Meta API:
    - campaign_id: The campaign ID (from campaign.custom_facebook_campaign_id)
    - name: Ad Set name (from ad_set.ad_set_name)
    - billing_event: How ad set is billed (IMPRESSIONS, CLICKS, ACTIONS, etc.)
    - optimization_goal: What to optimize for (REACH, IMPRESSIONS, LINK_CLICKS, etc.)
    - daily_budget OR lifetime_budget: Budget in minor units
    
    OPTIONAL FIELDS:
    - status: ACTIVE or PAUSED (defaults to PAUSED)
    - targeting: Audience targeting (geo, age, gender, device, etc.)
    - bid_strategy: LOWEST_COST_WITHOUT_CAP, etc.
    - bid_amount: Cap on bid (if required by bid_strategy)
    - start_time: Unix timestamp for ad set start
    - end_time: Unix timestamp for ad set end
    - is_dynamic_creative: Boolean for dynamic creative
    - daily_spend_cap: Daily spend limit in minor units
    - lifetime_spend_cap: Lifetime spend limit in minor units
    
    Args:
        ad_set_name: Frappe Ad Set document name
    
    Returns:
        dict with success, adset_id, and error_message (if applicable)
    """
    try:
        # Fetch the Ad Set document
        ad_set_doc = frappe.get_doc("Ad Set", ad_set_name)
        
        # ─── Validation ───────────────────────────────────────────────────
        if ad_set_doc.adset_id:
            return {
                "success": False,
                "message": _("Ad Set already created on Meta"),
                "error_message": f"Ad Set ID already exists: {ad_set_doc.adset_id}"
            }
        
        if not ad_set_doc.campaign:
            return {
                "success": False,
                "message": _("Campaign is required"),
                "error_message": _("No campaign selected for this Ad Set")
            }
        
        if not ad_set_doc.billing_event:
            return {
                "success": False,
                "message": _("Billing Event is required"),
                "error_message": _("Billing Event must be selected")
            }
        
        if not ad_set_doc.performance_goal:
            return {
                "success": False,
                "message": _("Optimization Goal is required"),
                "error_message": _("Optimization Goal must be selected")
            }
        
        # Fetch campaign document
        campaign_doc = frappe.get_doc("Marketing Campaign", ad_set_doc.campaign)
        
        if not campaign_doc.custom_facebook_campaign_id:
            return {
                "success": False,
                "message": _("Campaign has no Facebook Campaign ID"),
                "error_message": _("Please create the campaign on Meta first")
            }
        
        if not campaign_doc.custom_select_facebook_ad_account:
            return {
                "success": False,
                "message": _("Campaign has no Facebook Ad Account configured"),
                "error_message": _("Please configure the Facebook Ad Account for the campaign")
            }
        
        # ─── Budget Validation ────────────────────────────────────────────
        has_cbo = getattr(campaign_doc, 'custom_enable_adset_budget_sharing', False)
        if not has_cbo and (not ad_set_doc.amount or ad_set_doc.amount <= 0):
            return {
                "success": False,
                "message": _("Ad Set Amount is required"),
                "error_message": _("Budget amount must be greater than 0 (Campaign Budget Optimization is disabled)")
            }
        
        # ─── Build and Send Payload to Meta ───────────────────────────────
        logger.info(f"Creating Ad Set '{ad_set_doc.ad_set_name}' on Meta")
        
        provider = MetaAdsProvider(campaign_doc.custom_select_facebook_ad_account)
        payload = ad_set_doc._build_ad_set_payload(campaign_doc)
        
        logger.info(f"Ad Set Payload: {json.dumps(payload, indent=2, default=str)}")
        
        result = provider.create_ad_set(payload)
        
        if result.success:
            # ─── Save the adset_id back to Frappe ─────────────────────────
            ad_set_doc.adset_id = result.adset_id or getattr(result, 'campaign_id', None)
            ad_set_doc.save(ignore_permissions=True)
            
            logger.info(f"✅ Ad Set created on Meta with ID: {ad_set_doc.adset_id}")
            
            return {
                "success": True,
                "message": _("Ad Set created successfully on Meta"),
                "adset_id": ad_set_doc.adset_id
            }
        else:
            error_msg = result.error_message or "Unknown Meta error"
            logger.error(f"❌ Meta creation FAILED: {error_msg}")
            
            return {
                "success": False,
                "message": _("Failed to create Ad Set on Meta"),
                "error_message": error_msg
            }
    
    except frappe.DoesNotExistError:
        error_msg = f"Ad Set '{ad_set_name}' not found"
        logger.error(error_msg)
        return {
            "success": False,
            "message": _("Ad Set not found"),
            "error_message": error_msg
        }
    
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Exception during Ad Set Meta creation: {error_msg}")
        frappe.log_error(
            title="Ad Set Meta Creation Error",
            message=(
                f"Ad Set: {ad_set_name}\n"
                f"Error: {error_msg}\n"
                f"Traceback: {frappe.get_traceback()}"
            )
        )
        
        return {
            "success": False,
            "message": _("Error creating Ad Set on Meta"),
            "error_message": error_msg
        }