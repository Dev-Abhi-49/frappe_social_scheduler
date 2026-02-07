# Copyright (c) 2026, Abhishek and contributors
# For license information, please see license.txt

import frappe
import logging
from frappe import _
from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider

logger = logging.getLogger(__name__)


def marketing_campaign_before_save(doc, method=None):
    """
    Hook handler for Marketing Campaign before_save event
    Called via hooks.py
    """
    # Only create if new, Meta Ads checked, and no existing ID
    if doc.is_new() and getattr(doc, "custom_is_meta_ads", False) and not getattr(doc, "custom_facebook_campaign_id", None):
        create_meta_campaign(doc)


def create_meta_campaign(doc):
    """
    Create campaign via Meta Ads provider and store the campaign_id
    """
    try:
        # Basic validations (including Meta Ads check for safety)
        if not getattr(doc, "custom_is_meta_ads", False):
            return  # Skip silently if not Meta Ads

        # if not getattr(doc, "custom_select_facebook", None):
        #     frappe.throw(_("Select Facebook Ad Account is required"))
        if not getattr(doc, "custom_select_facebook_ad_account", None):
            frappe.throw(_("Select Ad Account is required"))
        if not getattr(doc, "custom_campaign_objective", None):
            frappe.throw(_("Campaign Objective is required"))

        # Parse Ad Account ID from selected value (format: "Name - act_XXXX")
        # selected_ad_account = getattr(doc, "custom_select_ad_account", "")
        # if ' - ' not in selected_ad_account:
        #     frappe.throw(_("Invalid Ad Account format"))
        # ad_account_name, ad_account_id = selected_ad_account.rsplit(' - ', 1)
        # ad_account_id = ad_account_id.strip()
        
        # integration = frappe.get_doc("Ads Account Integration", doc.custom_select_facebook)
        
        # if not integration.ad_account_id:
        #     frappe.throw(_("Selected account does not have an Ad Account ID configured"))

        
        # Initialize provider
        provider = MetaAdsProvider(doc.custom_select_facebook_ad_account)
        # provider.account_id = ad_account_id  # Set ad_account_id on provider

        # Build payload
        payload = build_campaign_payload(doc)

        logger.info(f"Creating campaign '{doc.custom_campaign_name}' on Meta Ads with payload: {payload}")

        # Create campaign
        result = provider.create_campaign(payload)

        if result.success:
            # Store the returned campaign ID (PublishResult uses post_id)
            doc.custom_facebook_campaign_id = result.campaign_id
            logger.info(f"✓ Campaign created successfully on Meta: {result.campaign_id}")
            frappe.msgprint(
                _("Campaign created successfully on Meta Ads. ID: {0}").format(result.campaign_id),
                alert=True,
            )
        else:
            error_msg = result.error_message or "Unknown error from Meta API"
            logger.error(f"Failed to create campaign on Meta: {error_msg}")
            frappe.throw(_("Failed to create campaign on Meta Ads: {0}").format(error_msg))

    except frappe.DoesNotExistError:
        frappe.throw(
            _("Facebook Integration '{0}' does not exist or is invalid.").format(doc.custom_select_facebook_ad_account)
        )
    except ValueError as e:
        frappe.throw(_("Invalid configuration: {0}").format(str(e)))
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Unexpected error creating campaign: {error_msg}")
        frappe.log_error(frappe.get_traceback(), "Marketing Campaign Creation Error")
        frappe.throw(_("Failed to create campaign: {0}").format(error_msg))


def build_campaign_payload(doc) -> dict:
    """
    Build and validate campaign payload with all mappings and transformations
    """
    # Map campaign objectives to Meta API format (from Meta docs)
    objective_map = {
        "Awareness": "OUTCOME_AWARENESS",
        "Traffic": "OUTCOME_TRAFFIC",
        "Engagement": "OUTCOME_ENGAGEMENT",
        "Leads": "OUTCOME_LEADS",
        "Sales": "OUTCOME_SALES",
        "App promotion": "OUTCOME_APP_PROMOTION",
    }
    objective = objective_map.get(doc.custom_campaign_objective)
    if not objective:
        frappe.throw(_("Invalid Campaign Objective selected"))

    # Map special ad categories to Meta format (MUST be array)
    special_ad_categories = ["NONE"]
    if getattr(doc, "custom_special_ad_categories", None) and doc.custom_special_ad_categories != "NONE":
        cat_map = {
            "None":"NONE",
            "Housing": "HOUSING",
            "Employment": "EMPLOYMENT",
            "Financial products and services": "CREDIT",
            "Social issues, elections or politics": "ISSUES_ELECTIONS_POLITICS",
        }
        mapped_cat = cat_map.get(doc.custom_special_ad_categories)
        if not mapped_cat:
            frappe.throw(_("Invalid Special Ad Category selected"))
        special_ad_categories = [mapped_cat]

    # Map buying type to Meta format
    buying_type_map = {
        "Auction": "AUCTION",
        "Reservation": "RESERVATION",
    }
    buying_type = buying_type_map.get(getattr(doc, "custom_choose_buying_type", ""), "AUCTION")

    # Build final payload - only send what Meta API expects
    payload = {
        "name": doc.custom_campaign_name,
        "objective": objective,
        "status": "ACTIVE" if doc.custom_is_meta_ads else "PAUSED",  # Recommended: start PAUSED for safety
        "buying_type": buying_type,
        "special_ad_categories": special_ad_categories,
        "is_adset_budget_sharing_enabled": True if doc.custom_enable_adset_budget_sharing else False,  # Set to False (not a valid field for campaign creation in most cases)
    }

    return payload