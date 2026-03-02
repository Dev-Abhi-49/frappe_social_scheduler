import frappe
from frappe import _
from frappe.utils import get_datetime
from datetime import datetime

# Meta minimum spend cap in minor units (₹100 = 10000 paise)
SPEND_CAP_MIN_MINOR = 10000

# Allowed ODAX objectives (v25.0)
ALLOWED_OBJECTIVES = [
    "OUTCOME_AWARENESS",
    "OUTCOME_TRAFFIC",
    "OUTCOME_ENGAGEMENT",
    "OUTCOME_LEADS",
    "OUTCOME_SALES",
    "OUTCOME_APP_PROMOTION",
]

BID_STRATEGIES_REQUIRING_CAP = [
    "LOWEST_COST_WITH_BID_CAP",
    "COST_CAP",
]

META_GRAPH_VERSION = "v25.0"
META_GRAPH_BASE = f"https://graph.facebook.com/{META_GRAPH_VERSION}"


def build_campaign_payload(doc) -> dict:
    """
    Build validated Meta Campaign payload (v25.0).

    IMPORTANT: Ad Labels must be resolved (IDs obtained) BEFORE calling this
    function. Call resolve_and_persist_ad_label_ids() first when labels are
    present. This function expects label IDs already stored in
    doc.custom_ad_campaign_labels[*].label_id.
    """

    # ----------------------------
    # VALIDATION
    # ----------------------------
    _validate_required_fields(doc)
    _validate_objective(doc)
    _validate_budget_rules(doc)
    _validate_bid_strategy(doc)
    _validate_spend_cap(doc)
    _validate_budget_schedule_specs(doc)
    _validate_campaign_optimization_type(doc)

    # ----------------------------
    # BASE PAYLOAD
    # ----------------------------
    special_ad_categories = _build_special_ad_categories(doc)

    payload = {
        "name": doc.custom_campaign_name.strip(),
        "objective": doc.custom_campaign_objective,
        # Use the dedicated status Select field (PAUSED / ACTIVE / ARCHIVED).
        # Fall back to PAUSED if somehow blank — Meta requires a valid value.
        "status": "ACTIVE" if doc.custom_enable_campaign else "PAUSED",
        "buying_type": doc.custom_choose_buying_type or "AUCTION",
        "special_ad_categories": special_ad_categories,
    }

    # ----------------------------
    # Special Ad Category Countries
    # Required when a real special category is selected (not just the ["NONE"] sentinel).
    # ----------------------------
    if special_ad_categories != ["NONE"]:
        countries = _build_special_ad_category_country(doc)
        if countries:
            payload["special_ad_category_countries"] = countries

    # ----------------------------
    # CBO (Advantage+ Campaign Budget)
    # Activated by setting daily_budget or lifetime_budget at campaign level.
    # ----------------------------
    if doc.custom_enable_adset_budget_sharing:
        budget_minor = int(float(doc.custom_budget_amount) * 100)
        if doc.custom_budget_type_dailylifetime == "Lifetime budget":
            payload["lifetime_budget"] = budget_minor
        else:
            payload["daily_budget"] = budget_minor

    # ----------------------------
    # Start / End Time
    # ----------------------------
    if doc.custom_start_date_and_time:
        payload["start_time"] = _to_iso(doc.custom_start_date_and_time)

    if doc.custom_end_date_and_time:
        payload["stop_time"] = _to_iso(doc.custom_end_date_and_time)

    # ----------------------------
    # Bid Strategy
    # ----------------------------
    if doc.custom_campaign_bid_strategy_:
        payload["bid_strategy"] = doc.custom_campaign_bid_strategy_

        if doc.custom_campaign_bid_strategy_ in BID_STRATEGIES_REQUIRING_CAP:
            payload["bid_amount"] = int(float(doc.custom_bid_amount) * 100)

        # ROAS strategy uses roas_average_floor, NOT bid_amount.
        # Meta expects this as an integer in units of 0.01
        # (e.g. a 2.0x ROAS target → send 200).
        if doc.custom_campaign_bid_strategy_ == "LOWEST_COST_WITH_MIN_ROAS":
            payload["roas_average_floor"] = int(float(doc.custom_roas_value) * 100)

    # ----------------------------
    # Spend Cap
    # ----------------------------
    if doc.custom_add_campaign_spending_limit:
        payload["spend_cap"] = int(float(doc.custom_add_campaign_spending_limit) * 100)

    # ----------------------------
    # Campaign Optimization Type
    # Only send to Meta when explicitly set to "ICO_ONLY".
    # The Select field defaults to the string "NONE" which should be omitted
    # from the payload entirely (Meta doesn't accept "NONE" as a value here).
    # ----------------------------
    opt_type = getattr(doc, "custom_campaign_optimization_type", None)
    if opt_type and opt_type == "ICO_ONLY":
        payload["campaign_optimization_type"] = opt_type

    # ----------------------------
    # Promoted Object
    # ----------------------------
    promoted_object = _build_promoted_object(doc)
    if promoted_object:
        payload["promoted_object"] = promoted_object

    # ----------------------------
    # Budget Schedule Specs (RESERVED campaigns only)
    # ----------------------------
    if (
        doc.custom_choose_buying_type == "RESERVED"
        and getattr(doc, "custom_budget_schedule_specs", None)
    ):
        specs = _build_budget_schedule_specs(doc)
        if specs:
            payload["budget_schedule_specs"] = specs

    # ----------------------------
    # Ad Labels
    # IDs must be pre-resolved. Format: [{"id": "label_id_1"}, ...]
    # ----------------------------
    ad_label_refs = _build_ad_label_id_refs(doc)
    if ad_label_refs:
        payload["adlabels"] = ad_label_refs

    return payload


# =========================================================
# AD LABEL RESOLUTION  (Step that must run before payload build)
# =========================================================

def resolve_and_persist_ad_label_ids(doc, access_token: str) -> None:
    """
    Resolves Meta AdLabel IDs for every row in doc.custom_ad_campaign_labels.

    For each row:
      - If label_id is already set → skip (already created/cached from a prior run).
      - If label_id is blank:
          1. Fetch all existing labels on the account once (to avoid duplicates).
          2. If a label with the same name already exists → reuse its ID.
          3. If not found → create it via  POST /act_{account}/adlabels  and store ID.

    The doc is saved at the end so label_ids persist for future use.

    Args:
        doc:          Marketing Campaign Frappe document
        access_token: Valid Meta API access token
    """
    labels = getattr(doc, "custom_ad_campaign_labels", None) or []
    if not labels:
        return

    ad_account_id = _normalise_account_id(doc.custom_select_facebook_ad_account)

    # Fetch all existing labels from Meta once → build a name→id lookup
    existing_labels = _fetch_existing_ad_labels(ad_account_id, access_token)
    existing_by_name = {v["name"].lower(): v["id"] for v in existing_labels}

    updated = False

    for row in labels:
        label_name = (row.label_name or "").strip()
        if not label_name:
            continue

        # Already resolved in a previous run — nothing to do
        if getattr(row, "label_id", None):
            frappe.logger().info(
                f"[AdLabel] '{label_name}' already resolved → ID {row.label_id}"
            )
            continue

        if label_name.lower() in existing_by_name:
            # ── Reuse existing label ──────────────────────────────────────
            row.label_id = existing_by_name[label_name.lower()]
            updated = True
            frappe.logger().info(
                f"[AdLabel] Reusing existing label '{label_name}' → ID {row.label_id}"
            )
        else:
            # ── Create new label on Meta ──────────────────────────────────
            label_id = _create_ad_label_on_meta(ad_account_id, label_name, access_token)
            row.label_id = label_id
            # Cache locally so a duplicate name in a later row is also reused
            existing_by_name[label_name.lower()] = label_id
            updated = True
            frappe.logger().info(
                f"[AdLabel] Created new label '{label_name}' → ID {label_id}"
            )

    if updated:
        # Persist label IDs back to Frappe so they survive future saves
        doc.save(ignore_permissions=True)


def _normalise_account_id(account_id: str) -> str:
    """Ensure the account ID always has the required act_ prefix."""
    if not account_id.startswith("act_"):
        return f"act_{account_id}"
    return account_id


def _fetch_existing_ad_labels(ad_account_id: str, access_token: str) -> list:
    """
    GET /act_{ad_account_id}/adlabels?fields=id,name&limit=200

    Follows cursor-based pagination to retrieve ALL labels on the account.
    Returns a list of {"id": "...", "name": "..."} dicts.
    On network/API failure: logs the error and returns an empty list
    (non-fatal — we will attempt creation and let Meta reject true duplicates).
    """
    import requests

    url = f"{META_GRAPH_BASE}/{ad_account_id}/adlabels"
    params = {
        "fields": "id,name",
        "limit": 200,
        "access_token": access_token,
    }

    all_labels = []

    while url:
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            frappe.log_error(
                title="Meta AdLabel Fetch Error",
                message=f"Failed to fetch existing ad labels from {ad_account_id}: {exc}",
            )
            break  # non-fatal

        if "error" in data:
            frappe.log_error(
                title="Meta AdLabel Fetch API Error",
                message=f"Meta error fetching labels: {data['error']}",
            )
            break

        all_labels.extend(data.get("data", []))

        # Follow cursor pagination
        next_url = data.get("paging", {}).get("next")
        if next_url:
            url = next_url
            params = {}  # all params are already embedded in the next URL
        else:
            break

    return all_labels


def _create_ad_label_on_meta(ad_account_id: str, label_name: str, access_token: str) -> str:
    """
    POST /act_{ad_account_id}/adlabels
    Request body: { "name": "<label_name>", "access_token": "<token>" }

    Meta API response on success:
        { "id": "23847392847392847" }

    Returns:
        The new label's ID string.

    Raises:
        frappe.ValidationError on any API or network failure.
    """
    import requests

    url = f"{META_GRAPH_BASE}/{ad_account_id}/adlabels"
    body = {
        "name": label_name,
        "access_token": access_token,
    }

    try:
        resp = requests.post(url, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        frappe.throw(
            _("Network error while creating ad label '{0}': {1}").format(label_name, str(exc))
        )

    # Meta returns errors as JSON even on HTTP 200 in some cases
    if "error" in data:
        err = data["error"]
        frappe.throw(
            _("Meta API error creating ad label '{0}': [{1}] {2}").format(
                label_name,
                err.get("code", "?"),
                err.get("message", "Unknown error"),
            )
        )

    label_id = data.get("id")
    if not label_id:
        frappe.throw(
            _("Meta did not return an ID for ad label '{0}'. Response: {1}").format(
                label_name, str(data)
            )
        )

    return label_id


def _build_ad_label_id_refs(doc) -> list:
    """
    Build the adlabels list for the campaign payload.

    Meta Campaign API expects:
        "adlabels": [{"id": "label_id_1"}, {"id": "label_id_2"}, ...]

    Skips rows with no label_id (with a warning logged) so that a partial
    failure in label creation does not silently block campaign creation.
    """
    refs = []
    for row in getattr(doc, "custom_ad_campaign_labels", []) or []:
        label_name = (row.label_name or "").strip()
        label_id = getattr(row, "label_id", None)

        if not label_name:
            continue  # blank rows are silently skipped

        if label_id:
            refs.append({"id": label_id})
        else:
            frappe.log_error(
                title="AdLabel ID Not Resolved",
                message=(
                    f"Label '{label_name}' has no label_id. "
                    f"It will NOT be attached to the campaign. "
                    f"Ensure resolve_and_persist_ad_label_ids() ran before building the payload."
                ),
            )
    return refs


# =========================================================
# VALIDATION HELPERS
# =========================================================

def _validate_required_fields(doc):
    if not doc.custom_campaign_name:
        frappe.throw(_("Campaign Name is required"))
    if not doc.custom_campaign_objective:
        frappe.throw(_("Campaign Objective is required"))
    if not doc.custom_select_facebook_ad_account:
        frappe.throw(_("Facebook Ad Account is required"))


def _validate_objective(doc):
    if doc.custom_campaign_objective not in ALLOWED_OBJECTIVES:
        frappe.throw(
            _("Invalid objective. Must be one of: {0}").format(", ".join(ALLOWED_OBJECTIVES))
        )


def _validate_budget_rules(doc):
    if doc.custom_enable_adset_budget_sharing:
        if not doc.custom_budget_amount:
            frappe.throw(_("Budget Amount is required when CBO is enabled"))
        if doc.custom_budget_type_dailylifetime == "Lifetime budget":
            if not doc.custom_start_date_and_time:
                frappe.throw(_("Start time is required for Lifetime Budget"))
    else:
        if doc.custom_budget_amount:
            frappe.throw(
                _("Disable campaign budget when CBO is off (budget must be at Ad Set level)")
            )


def _validate_bid_strategy(doc):
    strategy = doc.custom_campaign_bid_strategy_
    if strategy in BID_STRATEGIES_REQUIRING_CAP:
        if not getattr(doc, "custom_bid_amount", None):
            frappe.throw(_("Bid Amount is required for selected Bid Strategy"))
    if strategy == "LOWEST_COST_WITH_MIN_ROAS":
        if not getattr(doc, "custom_roas_value", None):
            frappe.throw(_("ROAS value is required for MIN_ROAS strategy"))


def _validate_spend_cap(doc):
    if doc.custom_add_campaign_spending_limit:
        spend_minor = int(float(doc.custom_add_campaign_spending_limit) * 100)
        if spend_minor < SPEND_CAP_MIN_MINOR:
            frappe.throw(
                _("Spend cap must be at least {0} (minor currency units)").format(
                    SPEND_CAP_MIN_MINOR
                )
            )


def _validate_budget_schedule_specs(doc):
    if not getattr(doc, "custom_budget_schedule_specs", None):
        return
    if doc.custom_choose_buying_type != "RESERVED":
        frappe.throw(_("Budget Schedule Specs only allowed for RESERVED campaigns"))
    for row in doc.custom_budget_schedule_specs:
        if not row.time_start:
            frappe.throw(_("Time Start is required in Budget Schedule Spec"))
        if not row.time_end:
            frappe.throw(_("Time End is required in Budget Schedule Spec"))
        if not row.budget_value or float(row.budget_value) <= 0:
            frappe.throw(_("Budget Value must be greater than 0 in Budget Schedule Spec"))


def _validate_campaign_optimization_type(doc):
    value = getattr(doc, "custom_campaign_optimization_type", None)

    # The Select field defaults to the string "NONE" (its first option).
    # Treat blank AND the literal "NONE" as "not configured" — nothing to validate.
    if not value or value == "NONE":
        return

    # Only "ICO_ONLY" is a meaningful value that requires further checks
    if value != "ICO_ONLY":
        frappe.throw(_("Invalid Campaign Optimization Type. Allowed values: NONE, ICO_ONLY."))

    if doc.custom_campaign_objective not in ["OUTCOME_SALES", "OUTCOME_APP_PROMOTION"]:
        frappe.throw(
            _("Campaign Optimization Type 'ICO_ONLY' is only allowed for "
              "Sales or App Promotion campaigns")
        )


# =========================================================
# PAYLOAD BUILDERS
# =========================================================

def _build_special_ad_categories(doc) -> list:
    categories = []
    if getattr(doc, "custom_housing", False):
        categories.append("HOUSING")
    if getattr(doc, "custom_employment", False):
        categories.append("EMPLOYMENT")
    if getattr(doc, "custom_financial_products_and_services", False):
        categories.append("CREDIT")
    if getattr(doc, "custom_social_issues_elections_or_politics", False):
        categories.append("ISSUES_ELECTIONS_POLITICS")
    return categories if categories else ["NONE"]


def _build_special_ad_category_country(doc) -> list:
    if not getattr(doc, "custom_special_ad_category_country", None):
        return []
    countries = []
    for row in doc.custom_special_ad_category_country:
        country_code = frappe.db.get_value("Country", row.country, "code")
        if not country_code:
            frappe.throw(
                _("Country '{0}' must have an ISO 2-letter code in the Country master").format(
                    row.country
                )
            )
        countries.append(country_code.upper())
    return countries


def _build_budget_schedule_specs(doc) -> list:
    specs = []
    for row in doc.custom_budget_schedule_specs or []:
        if not row.time_start or not row.time_end:
            frappe.throw(_("Time Start and Time End are required in Budget Schedule Specs"))
        if not row.budget_value:
            frappe.throw(_("Budget Value is required in Budget Schedule Specs"))
        spec = {
            "time_start": int(get_datetime(row.time_start).timestamp()),
            "time_end": int(get_datetime(row.time_end).timestamp()),
            "budget_value": int(float(row.budget_value) * 100),
            "budget_value_type": row.budget_value_type or "ABSOLUTE",
        }
        if row.recurrence_type:
            spec["recurrence_type"] = row.recurrence_type
        specs.append(spec)
    return specs


def _build_promoted_object(doc) -> dict | None:
    if not doc.custom_promoted_object_type or doc.custom_promoted_object_type == "None":
        return None

    po = {}

    if doc.custom_promoted_object_type == "Pixel":
        if not doc.custom_pixel_id:
            frappe.throw(_("Pixel ID is required for Pixel promoted object"))
        po["pixel_id"] = doc.custom_pixel_id
        if doc.custom_custom_event_type:
            po["custom_event_type"] = doc.custom_custom_event_type
        if doc.custom_value_semantic_type:
            po["value_semantic_type"] = doc.custom_value_semantic_type

    elif doc.custom_promoted_object_type == "App":
        if not doc.custom_application_id:
            frappe.throw(_("Application ID is required for App promoted object"))
        po["application_id"] = doc.custom_application_id
        if doc.custom_object_store_url:
            po["object_store_url"] = doc.custom_object_store_url
        if doc.custom_custom_event_type:
            po["custom_event_type"] = doc.custom_custom_event_type

    elif doc.custom_promoted_object_type == "Product Catalog":
        if not doc.custom_product_catalog_id:
            frappe.throw(_("Product Catalog ID is required"))
        po["product_catalog_id"] = doc.custom_product_catalog_id
        if doc.custom_product_set_id:
            po["product_set_id"] = doc.custom_product_set_id
        if doc.custom_product_sales_channel:
            po["product_sales_channel"] = doc.custom_product_sales_channel

    elif doc.custom_promoted_object_type == "Page":
        if not doc.custom_page_id:
            frappe.throw(_("Page ID is required for Page promoted object"))
        po["page_id"] = doc.custom_page_id

    elif doc.custom_promoted_object_type == "Instagram Profile":
        if not doc.custom_instagram_profile_id:
            frappe.throw(_("Instagram Profile ID is required"))
        po["instagram_profile_id"] = doc.custom_instagram_profile_id

    elif doc.custom_promoted_object_type == "Event":
        if not doc.custom_event_id:
            frappe.throw(_("Event ID is required for Event promoted object"))
        po["event_id"] = doc.custom_event_id

    elif doc.custom_promoted_object_type == "Lead Ads":
        if not doc.custom_page_id:
            frappe.throw(_("Page ID is required for Lead Ads promoted object"))
        po["page_id"] = doc.custom_page_id

    elif doc.custom_promoted_object_type == "Offline Dataset":
        if not doc.custom_offline_dataset_id:
            frappe.throw(_("Offline Dataset ID is required"))
        po["offline_conversion_data_set_id"] = doc.custom_offline_dataset_id

    return po if po else None


def _to_iso(dt_value) -> str:
    if isinstance(dt_value, datetime):
        return dt_value.isoformat()
    return get_datetime(dt_value).isoformat()


def _get_access_token_for_account(ad_account_name: str) -> str:
    """
    Fetch the Meta access token from the Ads Account Integration doctype.
    Adjust the field name 'access_token' to match your actual doctype.
    """
    token = frappe.db.get_value("Ads Account Integration", ad_account_name, "access_token")
    if not token:
        frappe.throw(
            _("No access token found for Ad Account '{0}'. Please reconnect the account.").format(
                ad_account_name
            )
        )
    return token


# =========================================================
# WHITELISTED API
# =========================================================

@frappe.whitelist()
def create_campaign_on_meta(campaign_name: str) -> dict:
    """
    Full Meta campaign creation flow:

      Step 1 — Resolve / create ad labels on Meta (get their IDs)
               POST /act_{account_id}/adlabels  for each unresolved label
      Step 2 — Build validated campaign payload (using resolved label IDs)
      Step 3 — POST to Meta Campaigns API
               POST /act_{account_id}/campaigns
      Step 4 — Store returned campaign_id in Frappe

    The "adlabels" field in the campaign payload is:
        [{"id": "label_id_1"}, {"id": "label_id_2"}, ...]

    Args:
        campaign_name: Name of the Marketing Campaign document

    Returns:
        dict with keys: success, campaign_id, message, is_new
    """
    import logging
    from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider

    logger = logging.getLogger(__name__)

    try:
        campaign_doc = frappe.get_doc("Marketing Campaign", campaign_name)

        # ── Guard checks ──────────────────────────────────────────────────
        if not campaign_doc.custom_is_meta_ads:
            frappe.throw(_("Meta Ads is not enabled for this campaign"))

        if not campaign_doc.custom_select_facebook_ad_account:
            frappe.throw(_("Facebook Ad Account is required"))

        if campaign_doc.custom_facebook_campaign_id:
            return {
                "success": True,
                "message": _("Campaign already created on Meta"),
                "campaign_id": campaign_doc.custom_facebook_campaign_id,
                "is_new": False,
            }

        # ── Step 1: Resolve ad label IDs ─────────────────────────────────
        ad_labels = getattr(campaign_doc, "custom_ad_campaign_labels", None) or []
        if ad_labels:
            logger.info(f"[{campaign_name}] Resolving {len(ad_labels)} ad label(s) on Meta...")

            access_token = _get_access_token_for_account(
                campaign_doc.custom_select_facebook_ad_account
            )
            # Creates missing labels via POST /act_{account}/adlabels
            # and persists their IDs in the child table rows.
            resolve_and_persist_ad_label_ids(campaign_doc, access_token)

            # Reload so the saved label_ids are visible in this doc instance
            campaign_doc.reload()
            logger.info(f"[{campaign_name}] Ad labels resolved.")

        # ── Step 2: Build payload ─────────────────────────────────────────
        logger.info(f"[{campaign_name}] Building campaign payload...")
        payload = build_campaign_payload(campaign_doc)
        # At this point payload["adlabels"] = [{"id": "..."}, ...] if any labels exist

        # ── Step 3: POST to Meta ──────────────────────────────────────────
        ad_account = campaign_doc.custom_select_facebook_ad_account
        provider = MetaAdsProvider(ad_account)

        logger.info(f"[{campaign_name}] Posting campaign to Meta: {payload.get('name')}")
        logger.info(f"[{campaign_name}] Full payload being sent: {payload}")

        result = provider.create_campaign(payload)

        if not result.success:
            # Log the full payload so we can pinpoint which field Meta rejected
            frappe.log_error(
                title="Meta Campaign Payload That Was Rejected",
                message=(
                    f"Campaign: {campaign_name}\n"
                    f"Error: {result.error_message}\n\n"
                    f"Payload sent:\n{frappe.as_json(payload)}"
                ),
            )
            frappe.throw(
                _("Failed to create campaign on Meta: {0}").format(result.error_message)
            )

        # ── Step 4: Persist campaign ID ───────────────────────────────────
        campaign_id = result.campaign_id
        logger.info(f"[{campaign_name}] Campaign created → ID: {campaign_id}")

        campaign_doc.custom_facebook_campaign_id = campaign_id
        campaign_doc.save()

        return {
            "success": True,
            "message": _("Campaign created successfully on Meta"),
            "campaign_id": campaign_id,
            "is_new": True,
        }

    except frappe.ValidationError as exc:
        frappe.log_error(title="Meta Campaign Validation Error", message=str(exc))
        frappe.throw(str(exc))
    except Exception as exc:
        error_msg = str(exc)
        frappe.log_error(
            title="Meta Campaign Creation Error",
            message=(
                f"Campaign: {campaign_name}\n"
                f"Error: {error_msg}\n"
                f"Traceback: {frappe.get_traceback()}"
            ),
        )
        frappe.throw(_("Error creating campaign on Meta: {0}").format(error_msg))


# =========================================================
# HOOKS
# =========================================================

def marketing_campaign_before_save(doc, method):
    """
    Before-save hook for Marketing Campaign.
    Validates all Meta fields. Does NOT resolve ad label IDs here —
    that requires a live API call and must happen via 'Create Campaign on Meta'.
    """
    if not doc.custom_is_meta_ads:
        return
    try:
        _validate_required_fields(doc)
        _validate_objective(doc)
        _validate_budget_rules(doc)
        _validate_bid_strategy(doc)
        _validate_spend_cap(doc)
        _validate_budget_schedule_specs(doc)
        _validate_campaign_optimization_type(doc)
    except frappe.ValidationError:
        raise