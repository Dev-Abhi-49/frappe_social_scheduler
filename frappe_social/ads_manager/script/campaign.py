# # Copyright (c) 2026, Abhishek and contributors
# # For license information, please see license.txt

# import frappe
# import logging
# from frappe import _
# from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider

# logger = logging.getLogger(__name__)


# def marketing_campaign_before_save(doc, method=None):
#     """
#     Hook handler for Marketing Campaign before_save event
#     Called via hooks.py
#     """
#     # Only create if new, Meta Ads checked, and no existing ID
#     if doc.is_new() and getattr(doc, "custom_is_meta_ads", False) and not getattr(doc, "custom_facebook_campaign_id", None):
#         create_meta_campaign(doc)


# def create_meta_campaign(doc):
#     """
#     Create campaign via Meta Ads provider and store the campaign_id
#     """
#     try:
#         # Basic validations (including Meta Ads check for safety)
#         if not getattr(doc, "custom_is_meta_ads", False):
#             return  # Skip silently if not Meta Ads

#         # if not getattr(doc, "custom_select_facebook", None):
#         #     frappe.throw(_("Select Facebook Ad Account is required"))
#         if not getattr(doc, "custom_select_facebook_ad_account", None):
#             frappe.throw(_("Select Ad Account is required"))
#         if not getattr(doc, "custom_campaign_objective", None):
#             frappe.throw(_("Campaign Objective is required"))
        
#         # Initialize provider
#         provider = MetaAdsProvider(doc.custom_select_facebook_ad_account)
#         # provider.account_id = ad_account_id  # Set ad_account_id on provider

#         # Build payload
#         payload = build_campaign_payload(doc)

#         logger.info(f"Creating campaign '{doc.custom_campaign_name}' on Meta Ads with payload: {payload}")

#         # Create campaign
#         result = provider.create_campaign(payload)

#         if result.success:
#             # Store the returned campaign ID (PublishResult uses post_id)
#             doc.custom_facebook_campaign_id = result.campaign_id
#             logger.info(f"✓ Campaign created successfully on Meta: {result.campaign_id}")
#             frappe.msgprint(
#                 _("Campaign created successfully on Meta Ads. ID: {0}").format(result.campaign_id),
#                 alert=True,
#             )
#         else:
#             error_msg = result.error_message or "Unknown error from Meta API"
#             logger.error(f"Failed to create campaign on Meta: {error_msg}")
#             frappe.throw(_("Failed to create campaign on Meta Ads: {0}").format(error_msg))

#     except frappe.DoesNotExistError:
#         frappe.throw(
#             _("Facebook Integration '{0}' does not exist or is invalid.").format(doc.custom_select_facebook_ad_account)
#         )
#     except ValueError as e:
#         frappe.throw(_("Invalid configuration: {0}").format(str(e)))
#     except Exception as e:
#         error_msg = str(e)
#         logger.error(f"Unexpected error creating campaign: {error_msg}")
#         frappe.log_error(frappe.get_traceback(), "Marketing Campaign Creation Error")
#         frappe.throw(_("Failed to create campaign: {0}").format(error_msg))


# def build_campaign_payload(doc) -> dict:
#     """
#     Build and validate campaign payload with all mappings and transformations
#     """
#     # Map campaign objectives to Meta API format (from Meta docs)
#     objective_map = {
#         "Awareness": "OUTCOME_AWARENESS",
#         "Traffic": "OUTCOME_TRAFFIC",
#         "Engagement": "OUTCOME_ENGAGEMENT",
#         "Leads": "OUTCOME_LEADS",
#         "Sales": "OUTCOME_SALES",
#         "App promotion": "OUTCOME_APP_PROMOTION",
#     }
#     objective = objective_map.get(doc.custom_campaign_objective)
#     if not objective:
#         frappe.throw(_("Invalid Campaign Objective selected"))

#     # Map special ad categories to Meta format (MUST be array)
#     special_ad_categories = ["NONE"]
#     if getattr(doc, "custom_special_ad_categories", None) and doc.custom_special_ad_categories != "NONE":
#         cat_map = {
#             "None":"NONE",
#             "Housing": "HOUSING",
#             "Employment": "EMPLOYMENT",
#             "Financial products and services": "CREDIT",
#             "Social issues, elections or politics": "ISSUES_ELECTIONS_POLITICS",
#         }
#         mapped_cat = cat_map.get(doc.custom_special_ad_categories)
#         if not mapped_cat:
#             frappe.throw(_("Invalid Special Ad Category selected"))
#         special_ad_categories = [mapped_cat]

#     # Map buying type to Meta format
#     buying_type_map = {
#         "Auction": "AUCTION",
#         "Reservation": "RESERVATION",
#     }
#     buying_type = buying_type_map.get(getattr(doc, "custom_choose_buying_type", ""), "AUCTION")

#     # Build final payload - only send what Meta API expects
#     payload = {
#         "name": doc.custom_campaign_name,
#         "objective": objective,
#         "status": "ACTIVE" if doc.custom_enable_campaign else "PAUSED",  # Recommended: start PAUSED for safety
#         "buying_type": buying_type,
#         "special_ad_categories": special_ad_categories,
#         "is_adset_budget_sharing_enabled": True if doc.custom_enable_adset_budget_sharing else False,  # Set to False (not a valid field for campaign creation in most cases)    
#     }

#     return payload

# Copyright (c) 2026, Abhishek and contributors
# For license information, please see license.txt

# Copyright (c) 2026, Abhishek and contributors
# For license information, please see license.txt

import frappe
import logging
from frappe import _
from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OBJECTIVE_MAP = {
    "Awareness":     "OUTCOME_AWARENESS",
    "Traffic":       "OUTCOME_TRAFFIC",
    "Engagement":    "OUTCOME_ENGAGEMENT",
    "Leads":         "OUTCOME_LEADS",
    "Sales":         "OUTCOME_SALES",
    "App promotion": "OUTCOME_APP_PROMOTION",
}

BID_STRATEGY_MAP = {
    "Highest volume":       "LOWEST_COST_WITHOUT_CAP",
    "Highest value":        "LOWEST_COST_WITHOUT_CAP",
    "Cost per result goal": "COST_CAP",
    "Bid cap":              "LOWEST_COST_WITH_BID_CAP",
    "Minimum ROAS":         "LOWEST_COST_WITH_MIN_ROAS",
}

BUYING_TYPE_MAP = {
    "Auction":     "AUCTION",
    "Reservation": "RESERVED",
}

SPECIAL_AD_CATEGORY_CHECKBOX_MAP = {
    "custom_housing":                             "HOUSING",
    "custom_employment":                          "EMPLOYMENT",
    "custom_financial_products_and_services":     "CREDIT",
    "custom_social_issues_elections_or_politics": "ISSUES_ELECTIONS_POLITICS",
}

# Meta minimum spend_cap in minor currency units (error 2446307 if below this)
# ₹100 in paise = 10000 | $1 in cents = 100
SPEND_CAP_MIN_MINOR = 10000


# ---------------------------------------------------------------------------
# Hook entry point
# ---------------------------------------------------------------------------

def marketing_campaign_before_save(doc, method=None):
    """Hook handler for Marketing Campaign before_save event"""
    if (
        doc.is_new()
        and getattr(doc, "custom_is_meta_ads", False)
        and not getattr(doc, "custom_facebook_campaign_id", None)
    ):
        create_meta_campaign(doc)


# ---------------------------------------------------------------------------
# Campaign creation
# ---------------------------------------------------------------------------

def create_meta_campaign(doc):
    """Create campaign via Meta Ads provider and store the campaign_id"""
    try:
        if not getattr(doc, "custom_is_meta_ads", False):
            return

        if not getattr(doc, "custom_select_facebook_ad_account", None):
            frappe.throw(_("Select Ad Account is required"))

        if not getattr(doc, "custom_campaign_objective", None):
            frappe.throw(_("Campaign Objective is required"))

        provider = MetaAdsProvider(doc.custom_select_facebook_ad_account)
        payload = build_campaign_payload(doc)

        logger.info(
            f"Creating campaign '{doc.custom_campaign_name}' on Meta Ads with payload: {payload}"
        )

        result = provider.create_campaign(payload)

        if result.success:
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

    except frappe.ValidationError:
        raise  # Re-raise user-facing validation errors as-is (prevents double-wrapping)

    except frappe.DoesNotExistError:
        frappe.throw(
            _("Facebook Integration '{0}' does not exist or is invalid.").format(
                doc.custom_select_facebook_ad_account
            )
        )
    except ValueError as e:
        frappe.throw(_("Invalid configuration: {0}").format(str(e)))
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Unexpected error creating campaign: {error_msg}")
        frappe.log_error(frappe.get_traceback(), "Marketing Campaign Creation Error")
        frappe.throw(_("Failed to create campaign: {0}").format(error_msg))


# ---------------------------------------------------------------------------
# Main payload builder
# ---------------------------------------------------------------------------

def build_campaign_payload(doc) -> dict:
    """
    Build a complete Facebook campaign creation payload from a Marketing Campaign doc.
    Reference: POST /act_{ad_account_id}/campaigns
    https://developers.facebook.com/docs/marketing-api/reference/ad-account/campaigns/
    """

    # ── 1. REQUIRED: name ────────────────────────────────────────────────────
    name = getattr(doc, "custom_campaign_name", None) or doc.name
    if not name:
        frappe.throw(_("Campaign name is required"))

    # ── 2. REQUIRED: objective ───────────────────────────────────────────────
    objective = OBJECTIVE_MAP.get(getattr(doc, "custom_campaign_objective", ""))
    if not objective:
        frappe.throw(_("Invalid or missing Campaign Objective"))

    # ── 3. REQUIRED: special_ad_categories (must always be a non-empty array) ─
    special_ad_categories = _build_special_ad_categories(doc)

    # ── 4. status — only ACTIVE / PAUSED allowed on creation ─────────────────
    status = "ACTIVE" if getattr(doc, "custom_enable_campaign", False) else "PAUSED"

    # ── 5. buying_type — AUCTION (default) or RESERVED ───────────────────────
    buying_type = BUYING_TYPE_MAP.get(
        getattr(doc, "custom_choose_buying_type", "Auction"), "AUCTION"
    )

    # ── Budget mode inputs ────────────────────────────────────────────────────
    is_adset_sharing = bool(getattr(doc, "custom_enable_adset_budget_sharing", False))
    budget_amount    = getattr(doc, "custom_budget_amount", None)
    budget_type      = getattr(doc, "custom_budget_type_dailylifetime", "Daily budget")

    # Warn when conflicting budget config is detected
    if is_adset_sharing and budget_amount:
        frappe.msgprint(
            _(
                "Campaign-level budget is ignored when Ad Set Budget Sharing is enabled. "
                "Budget must be set at the Ad Set level."
            ),
            alert=True,
            indicator="orange",
        )

    # ── Core payload (always present fields) ─────────────────────────────────
    payload = {
        "name":                  name,
        "objective":             objective,
        "status":                status,
        "buying_type":           buying_type,
        "special_ad_categories": special_ad_categories,
        "is_adset_budget_sharing_enabled": is_adset_sharing,
    }

    # ─────────────────────────────────────────────────────────────────────────
    # BUDGET MODE — three mutually exclusive cases
    #
    # ⚠️  NEVER send is_adset_budget_sharing_enabled: False explicitly.
    #     The Meta API only accepts True to OPT-IN to budget sharing.
    #     Passing False causes HTTP 400 error subcode 2446307.
    #     Omitting the field entirely = default disabled state.
    # ─────────────────────────────────────────────────────────────────────────

    # CASE 1: Ad Set Budget Sharing
    # Budgets stay at adset level; up to 20% can be shared across adsets.
    # bid_strategy is REQUIRED with this mode (error 4834005 if missing).
    if is_adset_sharing:
        payload["is_adset_budget_sharing_enabled"] = True  # ONLY send when True

        bid_strategy_label = getattr(doc, "custom_campaign_bid_strategy_", None)
        bid_strategy = BID_STRATEGY_MAP.get(
            bid_strategy_label or "Highest volume", "LOWEST_COST_WITHOUT_CAP"
        )
        payload["bid_strategy"] = bid_strategy  # Required in this mode

    # CASE 2: Campaign Budget Optimization (CBO)
    # Campaign-level budget auto-distributed across adsets.
    # Do NOT send is_adset_budget_sharing_enabled at all.
    elif budget_amount:
        budget_minor = int(float(budget_amount) * 100)  # major → minor currency units
        if budget_type == "Lifetime budget":
            payload["lifetime_budget"] = budget_minor
        else:
            payload["daily_budget"] = budget_minor

        # bid_strategy is optional but valid alongside CBO
        bid_strategy_label = getattr(doc, "custom_campaign_bid_strategy_", None)
        if bid_strategy_label:
            bid_strategy = BID_STRATEGY_MAP.get(bid_strategy_label)
            if bid_strategy:
                payload["bid_strategy"] = bid_strategy

    # CASE 3: Plain adset-level budget (no sharing, no CBO)
    # Simply omit is_adset_budget_sharing_enabled — Meta defaults to disabled.
    # DO NOT send False explicitly — it causes error 2446307.
    # else: pass  ← nothing to add; default state requires no field in payload

    # ── SPEND CAP ─────────────────────────────────────────────────────────────
    # Validates BEFORE hitting the API to avoid error 2446307 / 2238055.
    if getattr(doc, "custom_campaign_spending_limit", False):
        spend_cap_amount = getattr(doc, "custom_add_campaign_spending_limit", None)

        # Guard 1: toggle on but no amount entered
        if not spend_cap_amount or float(spend_cap_amount) <= 0:
            frappe.msgprint(
                _(
                    "Campaign Spending Limit toggle is enabled but no amount is set. "
                    "Spending limit will not be applied."
                ),
                alert=True,
                indicator="orange",
            )
        else:
            spend_cap_minor = int(float(spend_cap_amount) * 100)

            # Guard 2: below Meta's absolute minimum floor
            if spend_cap_minor < SPEND_CAP_MIN_MINOR:
                frappe.throw(
                    _(
                        "Campaign Spending Limit is too low. "
                        "Minimum allowed is ₹{0}. You entered ₹{1}."
                    ).format(SPEND_CAP_MIN_MINOR // 100, float(spend_cap_amount))
                )

            # Guard 3: spend_cap must be >= campaign budget when CBO is active
            campaign_budget_minor = payload.get("daily_budget") or payload.get("lifetime_budget", 0)
            if campaign_budget_minor and spend_cap_minor < campaign_budget_minor:
                frappe.throw(
                    _(
                        "Campaign Spending Limit (₹{0}) cannot be less than "
                        "the Campaign Budget (₹{1})."
                    ).format(spend_cap_minor // 100, campaign_budget_minor // 100)
                )

            payload["spend_cap"] = spend_cap_minor

    # ── BUDGET SCHEDULE SPECS ─────────────────────────────────────────────────
    if getattr(doc, "custom_enable_budget_scheduling", False):
        schedule_rows = getattr(doc, "custom_budget_schedule_periods", [])
        if schedule_rows:
            specs = _build_budget_schedule_specs(schedule_rows)
            if specs:
                payload["budget_schedule_specs"] = specs

    # ── SPECIAL AD CATEGORY COUNTRY ───────────────────────────────────────────
    # Required by Meta when any category other than NONE is selected
    if special_ad_categories != ["NONE"]:
        country = getattr(doc, "custom_special_ad_category_country", None)
        if country:
            payload["special_ad_category_country"] = (
                [c.strip() for c in country.split(",") if c.strip()]
                if isinstance(country, str)
                else list(country)
            )

    # ── FLIGHT DATES ──────────────────────────────────────────────────────────
    start_time = getattr(doc, "custom_start_time", None) or getattr(doc, "start_date", None)
    stop_time  = getattr(doc, "custom_stop_time", None)  or getattr(doc, "end_date", None)
    if start_time:
        payload["start_time"] = _to_iso(start_time)
    if stop_time:
        payload["stop_time"] = _to_iso(stop_time)

    # ── iOS 14 SKAdNetwork ────────────────────────────────────────────────────
    if getattr(doc, "custom_is_skadnetwork_attribution", False):
        payload["is_skadnetwork_attribution"] = True

    # ── PROMOTED OBJECT (required for App Promotion objective) ───────────────
    if objective == "OUTCOME_APP_PROMOTION":
        app_id = getattr(doc, "custom_promoted_app_id", None)
        if app_id:
            payload["promoted_object"] = {"application_id": app_id}

    # ── AD LABELS ─────────────────────────────────────────────────────────────
    adlabels_raw = getattr(doc, "custom_adlabels", None)
    if adlabels_raw:
        label_ids = (
            [l.strip() for l in adlabels_raw.split(",") if l.strip()]
            if isinstance(adlabels_raw, str)
            else list(adlabels_raw)
        )
        if label_ids:
            payload["adlabels"] = [{"id": lid} for lid in label_ids]

    # ── SOURCE CAMPAIGN ID (when duplicated from another campaign) ────────────
    # source_id = getattr(doc, "custom_source_campaign_id", None)
    # if source_id:
    #     payload["source_campaign_id"] = str(source_id)

    # ── TOPLINE ID (Reservation / Reach-and-Frequency buys only) ─────────────
    topline_id = getattr(doc, "custom_topline_id", None)
    if topline_id:
        payload["topline_id"] = str(topline_id)

    logger.debug(f"Final campaign payload: {payload}")
    return payload


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _build_special_ad_categories(doc) -> list:
    """
    Meta API: send [] when no special categories apply.
    "NONE" as a string value is rejected in API v17.0+ (use empty array instead).
    """
    categories = []

    # Priority 1: individual checkboxes (multi-category)
    for fieldname, api_value in SPECIAL_AD_CATEGORY_CHECKBOX_MAP.items():
        if getattr(doc, fieldname, False):
            categories.append(api_value)

    # Priority 2: single Select field fallback
    if not categories:
        cat_map = {
            "Housing":                              "HOUSING",
            "Employment":                           "EMPLOYMENT",
            "Financial products and services":      "CREDIT",
            "Social issues, elections or politics": "ISSUES_ELECTIONS_POLITICS",
        }
        sel    = getattr(doc, "custom_special_ad_categories", "None")
        mapped = cat_map.get(sel)  # Returns None for "None" — intentionally excluded
        if mapped:
            categories.append(mapped)

    # ✅ Return empty array when no categories — NOT ["NONE"]
    # Meta API v17.0+ rejects "NONE" as an enum string value
    return categories  # [] when empty, or ["HOUSING"] etc. when set



def _build_budget_schedule_specs(rows: list) -> list:
    """
    Convert child-table rows (Time Period for Budget) → budget_schedule_specs.
    Expected child fields:
        time_start        Datetime
        time_end          Datetime
        budget_value      Currency  (major units; multiplied ×100 for minor units)
        budget_value_type Select    ABSOLUTE | MULTIPLIER
        recurrence_type   Select    ONE_TIME | WEEKLY
    """
    import datetime

    def to_unix(dt):
        if isinstance(dt, datetime.datetime):
            return int(dt.timestamp())
        if isinstance(dt, datetime.date):
            return int(datetime.datetime.combine(dt, datetime.time()).timestamp())
        return int(dt)

    specs = []
    for row in rows:
        time_start = getattr(row, "time_start", None)
        time_end   = getattr(row, "time_end", None)
        budget_val = getattr(row, "budget_value", None)
        val_type   = (getattr(row, "budget_value_type", "ABSOLUTE") or "ABSOLUTE").upper()

        if not (time_start and time_end and budget_val):
            continue  # skip incomplete rows silently

        specs.append({
            "time_start":        to_unix(time_start),
            "time_end":          to_unix(time_end),
            "budget_value":      int(float(budget_val) * 100),
            "budget_value_type": val_type,
        })

    return specs


def _to_iso(value) -> str:
    """Convert Frappe date / datetime / string to ISO-8601 for Meta API."""
    import datetime
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(value, datetime.time()).isoformat()
    return str(value)

