"""
Meta Ads Provider - Direct calls to Meta Graph API (no SDK)
Handles Facebook and Instagram ad operations through Meta Graph API
"""

import requests
import frappe
import json
import logging
from frappe import _
from typing import Dict, Optional
from frappe_social.ads_manager.providers.base import (
    BaseProvider,
    PublishResult,
    AnalyticsResult,
    TokenRefreshResult,
    AudienceResult,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
MAX_RETRIES = 3


# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

def safe_int(val):
    """Convert API values to int, handling strings, dicts, lists, and None"""
    if val is None or val == "":
        return 0
    if isinstance(val, dict):
        if "value" in val:
            return safe_int(val["value"])
        return 0
    if isinstance(val, list):
        if len(val) == 0:
            return 0
        if isinstance(val[0], dict):
            return sum(safe_int(item.get("value", 0)) for item in val)
        return sum(safe_int(v) for v in val)
    if isinstance(val, str):
        try:
            return int(val)
        except (ValueError, TypeError):
            return 0
    try:
        return int(val) if val else 0
    except (ValueError, TypeError):
        return 0


def safe_float(val):
    """Convert API values to float, handling strings, dicts, lists, and None"""
    if val is None or val == "":
        return 0.0
    if isinstance(val, dict):
        if "value" in val:
            return safe_float(val["value"])
        return 0.0
    if isinstance(val, list):
        if len(val) == 0:
            return 0.0
        if isinstance(val[0], dict):
            return sum(safe_float(item.get("value", 0)) for item in val)
        return sum(safe_float(v) for v in val)
    if isinstance(val, str):
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0
    try:
        return float(val) if val else 0.0
    except (ValueError, TypeError):
        return 0.0


class MetaAdsProvider(BaseProvider):
    PLATFORM = "Meta"
    MAX_BUDGET = 100000
    SUPPORTS_IMAGES = True
    SUPPORTS_VIDEO = True
    DAILY_API_LIMIT = 200

    def __init__(self, integration_name: str = None):
        super().__init__(integration_name)
        try:
            self.api_version = self.settings.meta_api_version or "v25.0"
            self.integration = frappe.get_doc("Ads Account Integration", integration_name)
            self.base_url = f"https://graph.facebook.com/{self.api_version}"
            self.access_token = self.integration.get_access_token()
            self.account_id = self.integration.ad_account_id.strip()

            if not self.access_token:
                raise ValueError("No access token")
            if not self.account_id or not self.account_id.startswith("act_"):
                raise ValueError(f"Invalid ad_account_id: {self.account_id}")
        except Exception as e:
            logger.error(f"MetaAdsProvider init failed for {integration_name}: {e}")
            raise

    def _make_request(
        self, method: str, endpoint: str, params: Dict = None, json_data: Dict = None, headers: Dict = None, files: Dict = None
    ) -> Dict:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        default_headers = {"Content-Type": "application/json"}
        if headers:
            default_headers.update(headers)

        kwargs = {"headers": default_headers, "timeout": REQUEST_TIMEOUT}
        if method.upper() == "GET":
            kwargs["params"] = {**(params or {}), "access_token": self.access_token}
        else:
            if files:
                # For multipart file uploads, don't set Content-Type (requests will set it with boundary)
                kwargs.pop("headers", None)
                kwargs["files"] = files
            else:
                kwargs["json"] = json_data or {}
            kwargs["params"] = {"access_token": self.access_token}

        for attempt in range(MAX_RETRIES):
            try:
                # Log request details for debugging
                if method.upper() == "GET":
                    request_params = {**(params or {}), "access_token": "***HIDDEN***"}
                    if "insights" in endpoint:
                        logger.info(f"GET {endpoint}")
                        logger.info(f"Parameters: {json.dumps(request_params, indent=2, default=str)}")
                elif json_data and method.upper() == "POST":
                    logger.debug(f"Sending POST request to {endpoint}")
                    logger.debug(f"Payload size: {len(json.dumps(json_data))} bytes")
                    
                    # Log full payload for adcreatives endpoint for debugging
                    if "adcreatives" in endpoint:
                        logger.info(f"AdCreatives payload: {json.dumps(json_data, indent=2)}")
                
                response = requests.request(method.upper(), url, **kwargs)
                response.raise_for_status()
                data = response.json()
                
                # Log response details for insights
                if "insights" in endpoint:
                    logger.info(f"Response status: {response.status_code}")
                    logger.info(f"Response keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                    if isinstance(data, dict) and "data" in data:
                        logger.info(f"Data array length: {len(data.get('data', []))}")
                        if data.get("data"):
                            logger.info(f"First data item keys: {list(data['data'][0].keys())}")

                if "error" in data:
                    error = data["error"]
                    error_msg = (
                        f"[{error.get('code')}] {error.get('message')} "
                        f"(type: {error.get('type')}, subcode: {error.get('error_subcode', 'N/A')})"
                    )
                    logger.error(f"Meta API ERROR {endpoint}: {error_msg}")
                    raise ValueError(error_msg)

                self.increment_rate_limit()
                return data

            except requests.HTTPError as e:
                try:
                    err_data = e.response.json()
                    error = err_data.get("error", {})
                    error_code = error.get('error_subcode', error.get('code'))
                    
                    # Provide helpful error messages for common subcode errors
                    error_hints = {
                        1885183: (
                            "Invalid image URL (error 1885183). Possible causes:\n"
                            "\n1. NGROK DOMAIN ISSUES (Most Common):\n"
                            "   - ngrok URLs are often rate-limited by external APIs\n"
                            "   - Meta's servers may be blocked from accessing ngrok\n"
                            "   - Solution: Use a real domain or public IP, not ngrok\n"
                            "\n2. URL PARAMETERS:\n"
                            "   - URL must NOT have ?query=params or #fragments\n"
                            "   - Remove ?v=timestamp, ?token=xxx, etc.\n"
                            "\n3. ACCESSIBILITY:\n"
                            "   - URL must be publicly accessible (HTTPS recommended)\n"
                            "   - NOT localhost or /private/files/\n"
                            "   - NOT behind VPN or private network\n"
                            "\n4. FILE ISSUES:\n"
                            "   - File must exist and be downloadable\n"
                            "   - File size must be < 4MB for images\n"
                            "   - Proper Content-Type header required\n"
                            "\n🔧 QUICK FIX: If using ngrok, deploy to a real server instead"
                        ),
                        2446603: "Invalid parameter in object_story_spec - Ensure all required link_data fields are present and properly formatted. Check that 'link', 'description', 'picture' (if provided) are all valid.",
                        100: "Invalid parameter - Check all payload fields are correctly formatted.",
                        17: "User token error - Access token may have expired or lack required permissions.",
                        10: "Permission denied - Application may not have required permissions.",
                    }
                    
                    hint = error_hints.get(error_code, "")
                    error_msg = (
                        f"HTTP {e.response.status_code} [{error.get('code')}] "
                        f"{error.get('message', e.response.reason)} "
                        f"(subcode: {error.get('error_subcode', 'N/A')})"
                    )
                    if hint:
                        error_msg += f"\nHint: {hint}"
                except:
                    error_msg = f"HTTP {e.response.status_code}: {e.response.text[:500]}"
                logger.error(f"HTTP ERROR (attempt {attempt+1}/{MAX_RETRIES}): {error_msg}")
                if attempt == MAX_RETRIES - 1:
                    raise ValueError(error_msg)
            except requests.RequestException as e:
                logger.warning(f"Request failed (attempt {attempt+1}/{MAX_RETRIES}): {e}")
                if attempt == MAX_RETRIES - 1:
                    raise ValueError(f"Request failed after {MAX_RETRIES} attempts: {str(e)}")

    def create_campaign(self, payload: Dict) -> PublishResult:
        """
        Create Meta campaign with complete structure validation
        Endpoint: POST /act_{ad_account_id}/campaigns
        Reference: https://developers.facebook.com/docs/marketing-api/reference/ad-account/campaigns
        
        REQUIRED FIELDS:
        - name: Campaign name (string)
        - objective: Campaign objective (enum) - OUTCOME_* or legacy values
        - special_ad_categories: Array (required - use [] for NONE)
        
        OPTIONAL FIELDS:
        - status: ACTIVE (creates paused), PAUSED, ARCHIVED (default: PAUSED for safety)
        - buying_type: AUCTION (default) or RESERVED
        - is_adset_budget_sharing_enabled: bool (default: false)
        - daily_budget: numeric (in minor currency units)
        - lifetime_budget: numeric (in minor currency units)
        - start_time: ISO format datetime
        - stop_time: ISO format datetime
        - bid_strategy: LOWEST_COST_WITHOUT_CAP, LOWEST_COST_WITH_BID_CAP, COST_CAP, LOWEST_COST_WITH_MIN_ROAS
        - spend_cap: numeric (in minor currency units)
        """
        endpoint = f"{self.account_id}/campaigns"
        
        logger.info(f"Creating campaign on {endpoint}")
        logger.info(f"Campaign payload: {json.dumps(payload, indent=2, default=str)}")
        
        try:
            # ─── REQUIRED FIELD VALIDATION ───────────────────────────────────────
            
            # 1. Campaign Name (required)
            if not payload.get('name'):
                error_msg = "Campaign name is required"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            # 2. Objective (required)
            if not payload.get('objective'):
                error_msg = "Campaign objective is required"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            # Validate objective against allowed values
            valid_objectives = [
                # Outcome-Driven Ads Experiences (ODAX)
                "OUTCOME_AWARENESS",
                "OUTCOME_TRAFFIC", 
                "OUTCOME_ENGAGEMENT",
                "OUTCOME_LEADS",
                "OUTCOME_SALES",
                "OUTCOME_APP_PROMOTION",
                # Legacy objectives (deprecated but still supported)
                "BRAND_AWARENESS",
                "REACH",
                "LINK_CLICKS",
                "POST_ENGAGEMENT",
                "PAGE_LIKES",
                "STORE_VISITS",
                "OFFER_CLAIMS",
                "VIDEO_VIEWS",
                "LEAD_GENERATION",
                "MESSAGES",
                "LOCAL_AWARENESS",
                "CONVERSIONS",
                "APP_INSTALLS",
                "PRODUCT_CATALOG_SALES",
                "EVENT_RESPONSES"
            ]
            
            objective = payload.get('objective')
            if objective not in valid_objectives:
                error_msg = f"Invalid objective '{objective}'. Must be one of: {', '.join(valid_objectives)}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            # 3. Special Ad Categories (REQUIRED - must be array, never string)
            if 'special_ad_categories' not in payload:
                error_msg = "special_ad_categories field is required (use empty array [] for NONE)"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            special_ad_categories = payload.get('special_ad_categories', [])
            if not isinstance(special_ad_categories, list):
                error_msg = f"special_ad_categories must be an array, got {type(special_ad_categories)}"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            # special_ad_categories must NOT be empty
            if not special_ad_categories:
                error_msg = "special_ad_categories must contain at least one value (use ['NONE'] if no special categories apply)"
                logger.error(error_msg)
                raise ValueError(error_msg)
            
            # Valid special ad categories
            valid_categories = ["NONE", "HOUSING", "EMPLOYMENT", "CREDIT", "ISSUES_ELECTIONS_POLITICS"]
            for cat in special_ad_categories:
                if cat not in valid_categories:
                    error_msg = f"Invalid special ad category '{cat}'. Must be one of: {', '.join(valid_categories)}"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
            
            # ─── OPTIONAL FIELD VALIDATION ───────────────────────────────────────
            
            # Status validation
            if 'status' in payload:
                valid_statuses = ["ACTIVE", "PAUSED", "ARCHIVED", "DELETED"]
                status = payload.get('status')
                if status not in valid_statuses:
                    error_msg = f"Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
            else:
                # Default to PAUSED for safety (recommended by Meta)
                payload['status'] = "PAUSED"
                logger.info("Status not specified, defaulting to PAUSED")
            
            # Buying type validation
            if 'buying_type' in payload:
                valid_buying_types = ["AUCTION", "RESERVED"]
                buying_type = payload.get('buying_type')
                if buying_type not in valid_buying_types:
                    error_msg = f"Invalid buying_type '{buying_type}'. Must be one of: {', '.join(valid_buying_types)}"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
            
            # Bid strategy validation (only relevant for CBO)
            if 'bid_strategy' in payload:
                valid_bid_strategies = [
                    "LOWEST_COST_WITHOUT_CAP",
                    "LOWEST_COST_WITH_BID_CAP", 
                    "COST_CAP",
                    "LOWEST_COST_WITH_MIN_ROAS"
                ]
                bid_strategy = payload.get('bid_strategy')
                if bid_strategy not in valid_bid_strategies:
                    error_msg = f"Invalid bid_strategy '{bid_strategy}'. Must be one of: {', '.join(valid_bid_strategies)}"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
            
            # Budget validation (in minor currency units)
            if 'daily_budget' in payload:
                daily_budget = safe_int(payload.get('daily_budget'))
                if daily_budget <= 0:
                    error_msg = "daily_budget must be greater than 0"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
                # 100 currency units minimum in paise (₹1)
                if daily_budget < 100:
                    logger.warning(f"daily_budget {daily_budget} is very low (minimum 100)")
            
            if 'lifetime_budget' in payload:
                lifetime_budget = safe_int(payload.get('lifetime_budget'))
                if lifetime_budget <= 0:
                    error_msg = "lifetime_budget must be greater than 0"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
            
            # Spend cap validation
            if 'spend_cap' in payload:
                spend_cap = safe_int(payload.get('spend_cap'))
                if spend_cap <= 0:
                    error_msg = "spend_cap must be greater than 0"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
            
            # ─── CONFLICTING CONFIGURATION CHECKS ────────────────────────────────
            
            # Check for CBO + ad set budget sharing conflict
            is_adset_sharing = payload.get('is_adset_budget_sharing_enabled', False)
            has_daily_budget = 'daily_budget' in payload
            has_lifetime_budget = 'lifetime_budget' in payload
            
            if is_adset_sharing and (has_daily_budget or has_lifetime_budget):
                logger.warning("CBO with budget sharing enabled, campaign-level budgets will be ignored")
                # Remove campaign-level budgets if CBO is enabled
                payload.pop('daily_budget', None)
                payload.pop('lifetime_budget', None)
            
            # ──────────────────────────────────────────────────────────────────────
            # LOG FINAL PAYLOAD BEFORE SENDING
            # ──────────────────────────────────────────────────────────────────────
            logger.info("=" * 80)
            logger.info("FINAL PAYLOAD BEING SENT TO META API:")
            logger.info(f"Endpoint: POST {endpoint}")
            logger.info("Payload (JSON):")
            logger.info(json.dumps(payload, indent=2, default=str))
            logger.info("Payload (Key Summary):")
            logger.info(f"  - name: {payload.get('name')}")
            logger.info(f"  - objective: {payload.get('objective')}")
            logger.info(f"  - status: {payload.get('status')}")
            logger.info(f"  - special_ad_categories: {payload.get('special_ad_categories')}")
            logger.info(f"  - is_adset_budget_sharing_enabled: {payload.get('is_adset_budget_sharing_enabled', 'NOT SET')}")
            logger.info(f"  - daily_budget: {payload.get('daily_budget', 'NOT SET')}")
            logger.info(f"  - lifetime_budget: {payload.get('lifetime_budget', 'NOT SET')}")
            logger.info(f"  - bid_strategy: {payload.get('bid_strategy', 'NOT SET')}")
            logger.info(f"  - spend_cap: {payload.get('spend_cap', 'NOT SET')}")
            logger.info("=" * 80)
            
            # Make API request
            response = self._make_request("POST", endpoint, json_data=payload)
            
            # Handle API response
            if "error" in response:
                error_detail = response.get("error", {})
                error_msg = error_detail.get("message", str(error_detail)) if isinstance(error_detail, dict) else str(error_detail)
                logger.error(f"Campaign creation API error: {error_msg}")
                return PublishResult(success=False, error_message=f"Meta API Error: {error_msg}")
            
            campaign_id = response.get("id")
            if not campaign_id:
                error_msg = "No campaign ID returned from Meta API"
                logger.error(error_msg)
                return PublishResult(success=False, error_message=error_msg)
            
            logger.info(f"✓ Campaign created successfully on Meta: {campaign_id}")            
            return PublishResult(success=True, campaign_id=campaign_id, raw_response=response)
        
        except ValueError as e:
            error_msg = str(e)
            logger.error(f"Campaign creation validation failed: {error_msg}")
            frappe.log_error(
                title="Meta Campaign Creation Validation Error",
                message=(
                    f"Account ID: {self.account_id}\n"
                    f"Error: {error_msg}\n"
                    f"Payload: {json.dumps(payload, indent=2, default=str)}"
                ),
            )
            return PublishResult(success=False, error_message=error_msg)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Campaign creation FAILED: {error_msg}")
            frappe.log_error(
                title="Meta Campaign Creation Error",
                message=(
                    f"Account ID: {self.account_id}\n"
                    f"Error: {error_msg}\n"
                    f"Payload: {json.dumps(payload, indent=2, default=str)}\n"
                    f"Traceback: {frappe.get_traceback()}"
                ),
            )
            return PublishResult(success=False, error_message=error_msg)

    # def update_campaign(self, campaign_id: str, payload: Dict) -> PublishResult:
    #     """
    #     Update an existing Meta campaign
    #     Endpoint: POST /{campaign_id}
    #     Reference: https://developers.facebook.com/docs/marketing-api/get-started/manage-campaigns
        
    #     UPDATABLE FIELDS:
    #     - name: Campaign name
    #     - status: ACTIVE, PAUSED, ARCHIVED
    #     - objective: Campaign objective (limited - cannot change for some objectives)
    #     - buying_type: AUCTION or RESERVED
    #     - daily_budget: numeric
    #     - lifetime_budget: numeric
    #     - spend_cap: numeric
    #     - bid_strategy: Bid strategy for CBO campaigns
    #     - is_adset_budget_sharing_enabled: bool
        
    #     NOTE: Some fields cannot be changed after creation
    #     """
    #     endpoint = campaign_id
        
    #     logger.info(f"Updating campaign {campaign_id}")
    #     logger.info(f"Update payload: {json.dumps(payload, indent=2, default=str)}")
        
    #     try:
    #         # Validate campaign ID format
    #         if not campaign_id or not str(campaign_id).isdigit():
    #             error_msg = f"Invalid campaign ID format: {campaign_id}"
    #             logger.error(error_msg)
    #             raise ValueError(error_msg)
            
    #         # ─── STATUS UPDATE ───────────────────────────────────────────────────
    #         if 'status' in payload:
    #             valid_statuses = ["ACTIVE", "PAUSED", "ARCHIVED", "DELETED"]
    #             status = payload.get('status')
    #             if status not in valid_statuses:
    #                 error_msg = f"Invalid status '{status}'. Must be one of: {', '.join(valid_statuses)}"
    #                 logger.error(error_msg)
    #                 raise ValueError(error_msg)
    #             logger.info(f"Setting campaign status to: {status}")
            
    #         # ─── BUDGET UPDATES ──────────────────────────────────────────────────
    #         if 'daily_budget' in payload:
    #             daily_budget = safe_int(payload.get('daily_budget'))
    #             if daily_budget <= 0:
    #                 error_msg = "daily_budget must be greater than 0"
    #                 logger.error(error_msg)
    #                 raise ValueError(error_msg)
            
    #         if 'lifetime_budget' in payload:
    #             lifetime_budget = safe_int(payload.get('lifetime_budget'))
    #             if lifetime_budget <= 0:
    #                 error_msg = "lifetime_budget must be greater than 0"
    #                 logger.error(error_msg)
    #                 raise ValueError(error_msg)
            
    #         if 'spend_cap' in payload:
    #             spend_cap = safe_int(payload.get('spend_cap'))
    #             if spend_cap <= 0:
    #                 error_msg = "spend_cap must be greater than 0"
    #                 logger.error(error_msg)
    #                 raise ValueError(error_msg)
            
    #         # ─── BUYING TYPE UPDATES ────────────────────────────────────────────
    #         if 'buying_type' in payload:
    #             valid_buying_types = ["AUCTION", "RESERVED"]
    #             buying_type = payload.get('buying_type')
    #             if buying_type not in valid_buying_types:
    #                 error_msg = f"Invalid buying_type '{buying_type}'"
    #                 logger.error(error_msg)
    #                 raise ValueError(error_msg)
            
    #         # ─── BID STRATEGY UPDATES ────────────────────────────────────────────
    #         if 'bid_strategy' in payload:
    #             valid_bid_strategies = [
    #                 "LOWEST_COST_WITHOUT_CAP",
    #                 "LOWEST_COST_WITH_BID_CAP",
    #                 "COST_CAP",
    #                 "LOWEST_COST_WITH_MIN_ROAS"
    #             ]
    #             bid_strategy = payload.get('bid_strategy')
    #             if bid_strategy not in valid_bid_strategies:
    #                 error_msg = f"Invalid bid_strategy '{bid_strategy}'"
    #                 logger.error(error_msg)
    #                 raise ValueError(error_msg)
            
    #         # Make API request
    #         response = self._make_request("POST", endpoint, json_data=payload)
            
    #         if "error" in response:
    #             error_detail = response.get("error", {})
    #             error_msg = error_detail.get("message", str(error_detail)) if isinstance(error_detail, dict) else str(error_detail)
    #             logger.error(f"Campaign update API error: {error_msg}")
    #             return PublishResult(success=False, error_message=f"Meta API Error: {error_msg}")
            
    #         logger.info(f"✓ Campaign {campaign_id} updated successfully")
    #         return PublishResult(success=True, campaign_id=campaign_id, raw_response=response)
        
    #     except ValueError as e:
    #         error_msg = str(e)
    #         logger.error(f"Campaign update validation failed: {error_msg}")
    #         frappe.log_error(
    #             title="Meta Campaign Update Validation Error",
    #             message=(
    #                 f"Campaign ID: {campaign_id}\n"
    #                 f"Error: {error_msg}\n"
    #                 f"Payload: {json.dumps(payload, indent=2, default=str)}"
    #             ),
    #         )
    #         return PublishResult(success=False, error_message=error_msg)
    #     except Exception as e:
    #         error_msg = str(e)
    #         logger.error(f"Campaign update FAILED: {error_msg}")
    #         frappe.log_error(
    #             title="Meta Campaign Update Error",
    #             message=(
    #                 f"Campaign ID: {campaign_id}\n"
    #                 f"Error: {error_msg}\n"
    #                 f"Traceback: {frappe.get_traceback()}"
    #             ),
    #         )
    #         return PublishResult(success=False, error_message=error_msg)

    # def pause_campaign(self, campaign_id: str) -> PublishResult:
    #     """Pause a campaign by setting status to PAUSED"""
    #     logger.info(f"Pausing campaign {campaign_id}")
    #     return self.update_campaign(campaign_id, {"status": "PAUSED"})

    # def resume_campaign(self, campaign_id: str) -> PublishResult:
    #     """Resume a campaign by setting status to ACTIVE"""
    #     logger.info(f"Resuming campaign {campaign_id}")
    #     return self.update_campaign(campaign_id, {"status": "ACTIVE"})

    # def archive_campaign(self, campaign_id: str) -> PublishResult:
    #     """Archive a campaign by setting status to ARCHIVED"""
    #     logger.info(f"Archiving campaign {campaign_id}")
    #     return self.update_campaign(campaign_id, {"status": "ARCHIVED"})

    # def delete_campaign(self, campaign_id: str) -> PublishResult:
    #     """
    #     Delete a campaign
    #     Endpoint: DELETE /{campaign_id}
    #     Reference: https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group/#delete
    #     """
    #     endpoint = campaign_id
        
    #     logger.info(f"Deleting campaign {campaign_id}")
        
    #     try:
    #         if not campaign_id or not str(campaign_id).isdigit():
    #             error_msg = f"Invalid campaign ID format: {campaign_id}"
    #             logger.error(error_msg)
    #             raise ValueError(error_msg)
            
    #         response = self._make_request("DELETE", endpoint)
            
    #         if "error" in response:
    #             error_detail = response.get("error", {})
    #             error_msg = error_detail.get("message", str(error_detail)) if isinstance(error_detail, dict) else str(error_detail)
    #             logger.error(f"Campaign deletion API error: {error_msg}")
    #             return PublishResult(success=False, error_message=f"Meta API Error: {error_msg}")
            
    #         logger.info(f"✓ Campaign {campaign_id} deleted successfully")
    #         return PublishResult(success=True, campaign_id=campaign_id, raw_response=response)
        
    #     except Exception as e:
    #         error_msg = str(e)
    #         logger.error(f"Campaign deletion FAILED: {error_msg}")
    #         frappe.log_error(
    #             title="Meta Campaign Deletion Error",
    #             message=(
    #                 f"Campaign ID: {campaign_id}\n"
    #                 f"Error: {error_msg}\n"
    #                 f"Traceback: {frappe.get_traceback()}"
    #             ),
    #         )
    #         return PublishResult(success=False, error_message=error_msg)

    def create_ad_set(self, payload: dict) -> PublishResult:
        """Create Ad Set on Meta"""
        endpoint = f"{self.account_id}/adsets"
        logger.info(f"POST {endpoint} for Ad Set")

        try:
            for field in ["name", "campaign_id", "billing_event", "optimization_goal"]:
                if not payload.get(field):
                    raise ValueError(f"Missing required field: {field}")
                    
            response = self._make_request("POST", endpoint, json_data=payload)

            if "error" in response:
                err = response["error"]
                msg = f"[{err.get('code')}] {err.get('message')}"
                return PublishResult(success=False, error_message=msg)

            adset_id = response.get("id")
            logger.info(f"✓ Meta Ad Set created: {adset_id}")
            return PublishResult(success=True, adset_id=adset_id, raw_response=response)

        except Exception as e:
            logger.error(f"create_ad_set failed: {e}")
            return PublishResult(success=False, error_message=str(e))

    def upload_image(self, payload: Dict) -> PublishResult:
        """
        Upload a local image file to Meta's ad image library.

        Endpoint: POST /act_{id}/adimages
        Reference: https://developers.facebook.com/docs/marketing-api/reference/ad-account/adimages/

        Meta REQUIRES the multipart field name to be the file's basename, NOT a
        generic key like "file".  Using the wrong key causes Meta to respond with
        an empty images dict or no hash.

        Returns PublishResult with image_hash set on success.
        """
        endpoint = f"{self.account_id}/adimages"

        filename = payload.get("filename")
        if not filename:
            raise ValueError("Filename is required for image upload")

        import os
        basename = os.path.basename(filename)
        logger.info(f"Uploading image to Meta /adimages: {filename} (field name: '{basename}')")

        try:
            with open(filename, "rb") as f:
                # Field name MUST be the file's basename — Meta uses it as the
                # key in the response dict AND to identify the image in the library.
                files = {basename: (basename, f, "image/jpeg")}
                response = self._make_request("POST", endpoint, files=files)

            logger.info(f"Upload response: {json.dumps(response, indent=2, default=str)}")

            images = response.get("images", {})
            if not images:
                raise ValueError(f"Meta returned no images in upload response: {response}")

            # Meta keys the response by the field name used in the upload
            image_data = images.get(basename) or list(images.values())[0]
            image_hash = image_data.get("hash")
            image_url  = image_data.get("url", "")

            if not image_hash:
                raise ValueError(f"No hash in Meta upload response: {image_data}")

            logger.info(f"Image uploaded successfully — hash: {image_hash}, url: {image_url}")
            return PublishResult(
                success=True,
                image_hash=image_hash,
                image_url=image_url,
                raw_response=response,
            )

        except FileNotFoundError:
            error_msg = f"File not found on disk: {filename}"
            logger.error(f"❌ {error_msg}")
            return PublishResult(success=False, error_message=error_msg)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Image upload failed: {error_msg}")
            frappe.log_error(
                title="Meta Image Upload Failed",
                message=(
                    f"Filename: {filename}\n"
                    f"Error: {error_msg}\n"
                    f"Traceback: {frappe.get_traceback()}"
                )
            )
            return PublishResult(success=False, error_message=error_msg)

    def verify_image_hash(self, image_hash: str) -> bool:
        """
        Verify that an image hash exists in THIS ad account's image library.

        WHY NOT USE _make_request():
        _make_request merges params as a plain dict, which causes requests to
        URL-encode bracket characters: hashes[0] → hashes%5B0%5D.
        Meta ignores the unrecognised parameter and returns ALL images, making
        bool(data) always True — so stale hashes pass verification and cause
        error 1885183 at creative creation time.

        We call requests.get() directly with a list of tuples so brackets are
        sent unencoded, and we explicitly confirm the returned hash matches.

        Endpoint: GET /act_{id}/adimages?hashes[0]={hash}&fields=hash
        """
        if not image_hash:
            return False
        try:
            url = f"{self.base_url}/{self.account_id}/adimages"
            # Use list of tuples — requests sends these WITHOUT URL-encoding brackets
            params = [
                ("hashes[0]", image_hash),
                ("fields",    "hash"),
                ("access_token", self.access_token),
            ]
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                err = data["error"]
                logger.warning(
                    f"verify_image_hash API error [{err.get('code')}]: {err.get('message')}"
                )
                return False

            items = data.get("data", [])

            # Confirm the returned record actually matches our hash (not a false positive)
            matched = any(
                item.get("hash") == image_hash for item in items
            )

            if matched:
                logger.info(
                    f"image_hash '{image_hash}' verified in account {self.account_id}"
                )
            else:
                logger.warning(
                    f"image_hash '{image_hash}' NOT found in account {self.account_id} "
                    f"(API returned {len(items)} item(s) but none matched). Will re-upload."
                )
            return matched

        except Exception as e:
            logger.warning(f"verify_image_hash failed (will re-upload to be safe): {e}")
            return False
    
    def create_creative(self, payload: Dict, page_access_token: str = None) -> PublishResult:
        """
        Create Meta ad creative via Marketing API v25.0
        
        Reference: https://developers.facebook.com/docs/marketing-api/reference/ad-creative/
        
        Supports two main paths:
        
        1. **Existing Post** (object_story_id):
           - Use when promoting an already-published Facebook page post
           - Minimal payload: name + object_story_id
        
        2. **New Creative** (object_story_spec):
           - Create unpublished page post + turn it into an ad
           - Supports: single_image, carousel, collection, video
           - link_data (image/carousel/collection) OR video_data (videos)
        
        IMAGE HANDLING:
        - Single Image: use 'picture' URL (Meta downloads & caches)
        - Multiple Images (Carousel/Collection): use 'image_hash' (from image library)
        - Videos: use 'video_id' (uploaded via /advideos endpoint)
        
        Args:
            payload: Creative dict with structure validation
            page_access_token: Optional page token (for reference only)
        
        Returns:
            PublishResult with success status, creative_id, and details
        """
        endpoint = f"{self.account_id}/adcreatives"

        logger.info(f"Creating creative on endpoint: {endpoint}")
        logger.info(f"Payload keys: {list(payload.keys())}")

        try:
            # ─── REQUIRED: name field ───────────────────────────────────────────
            if not payload:
                raise ValueError("Payload is required")
            
            if not payload.get('name'):
                raise ValueError("Field 'name' is required (creative name)")
            
            # ─── PATH 1: Existing Post (object_story_id) ────────────────────────
            # Example: object_story_id = "123456789_987654321"
            if payload.get('object_story_id'):
                logger.info(f"Path: Using existing post (object_story_id)")
                logger.info(f"Post ID: {payload.get('object_story_id')}")
                
                # object_story_id path only needs name + object_story_id
                # Optional: instagram_actor_id for Instagram promotion
                response = self._make_request("POST", endpoint, json_data=payload)
                creative_id = response.get("id")

                if creative_id:
                    logger.info(f"✅ Creative created from existing post: {creative_id}")
                    return PublishResult(
                        success=True,
                        creative_id=creative_id,
                        raw_response=response
                    )
                else:
                    raise ValueError(f"No creative ID returned: {response}")
            
            # ─── PATH 2: New Creative (object_story_spec) ────────────────────────
            if not payload.get('object_story_spec'):
                raise ValueError(
                    "Either 'object_story_id' (existing post) "
                    "or 'object_story_spec' (new creative) is required"
                )
            
            story_spec = payload['object_story_spec']
            
            # Required in object_story_spec
            if not story_spec.get('page_id'):
                raise ValueError("'page_id' is required in object_story_spec")
            
            logger.info(f"Path: Creating new unpublished post")
            logger.info(f"Page ID: {story_spec.get('page_id')}")
            
            # ─── Validate story_spec content (link_data, video_data, etc.) ──────
            
            # Check for data types (one of: link_data, video_data, photo_data, etc.)
            has_link_data = bool(story_spec.get('link_data'))
            has_video_data = bool(story_spec.get('video_data'))
            has_photo_data = bool(story_spec.get('photo_data'))
            
            if not (has_link_data or has_video_data or has_photo_data):
                raise ValueError(
                    "object_story_spec must contain one of: "
                    "'link_data' (image/carousel/collection), "
                    "'video_data' (videos), or 'photo_data' (photo)"
                )
            
            # ─── LINK DATA Validation (image, carousel, collection) ────────────
            if has_link_data:
                link_data = story_spec['link_data']
                
                if not isinstance(link_data, dict):
                    raise ValueError("'link_data' must be a dictionary/object")
                
                logger.info(f"Creative type: Image/Carousel/Collection")
                logger.info(f"Link data keys: {list(link_data.keys())}")
                
                # Validate image handling
                if link_data.get('picture'):
                    logger.info(f"✓ Single Image: using 'picture' URL")
                    if not self._is_valid_image_url(link_data['picture']):
                        logger.warning(f"URL may be inaccessible: {link_data['picture'][:100]}...")
                elif link_data.get('image_hash'):
                    logger.info(f"✓ Image from library: using 'image_hash'")
                
                # Validate carousel with child_attachments
                if link_data.get('child_attachments'):
                    logger.info(f"Carousel format: {len(link_data['child_attachments'])} attachments")
                    for idx, attachment in enumerate(link_data['child_attachments']):
                        if attachment.get('image_hash'):
                            logger.info(f"  [{idx}] image_hash: {attachment['image_hash'][:20]}...")
                        elif attachment.get('picture'):
                            logger.info(f"  [{idx}] picture URL present")
                        if attachment.get('video_id'):
                            logger.info(f"  [{idx}] video_id: {attachment['video_id']}")
            
            # ─── VIDEO DATA Validation ──────────────────────────────────────────
            elif has_video_data:
                video_data = story_spec['video_data']
                
                if not isinstance(video_data, dict):
                    raise ValueError("'video_data' must be a dictionary/object")
                
                if not video_data.get('video_id'):
                    raise ValueError(
                        "Field 'video_id' is required in video_data. "
                        "Upload video via /act_XXX/advideos endpoint first."
                    )
                
                logger.info(f"✓ Video Creative")
                logger.info(f"Video ID: {video_data['video_id']}")
                logger.info(f"Video data keys: {list(video_data.keys())}")
            
            # ─── PHOTO DATA Validation ──────────────────────────────────────────
            elif has_photo_data:
                photo_data = story_spec['photo_data']
                
                if not isinstance(photo_data, dict):
                    raise ValueError("'photo_data' must be a dictionary/object")
                
                logger.info(f"✓ Photo Creative")
                logger.info(f"Photo data keys: {list(photo_data.keys())}")
            
            # ─── Send request to Meta API ────────────────────────────────────────
            logger.info(f"Sending creative creation request to Meta API...")
            response = self._make_request("POST", endpoint, json_data=payload)
            creative_id = response.get("id")

            if creative_id:
                logger.info(f"✅ Creative created successfully: {creative_id}")
                return PublishResult(
                    success=True,
                    creative_id=creative_id,
                    raw_response=response
                )
            else:
                raise ValueError(f"No creative ID in response: {response}")

        except ValueError as e:
            # Validation errors
            error_msg = str(e)
            logger.error(f"❌ Creative validation failed: {error_msg}")
            
            frappe.log_error(
                title="Meta Creative Validation Error",
                message=(
                    f"Account ID: {self.account_id}\n"
                    f"Validation Error: {error_msg}\n"
                    f"Payload: {json.dumps(payload, indent=2, default=str)}"
                )
            )
            
            return PublishResult(success=False, error_message=error_msg)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Creative creation failed: {error_msg}")
            
            frappe.log_error(
                title="Meta Creative Creation Failed",
                message=(
                    f"Account ID: {self.account_id}\n"
                    f"Payload: {json.dumps(payload, indent=2, default=str)}\n"
                    f"Error: {error_msg}\n"
                    f"Traceback: {frappe.get_traceback()}"
                )
            )
            
            return PublishResult(success=False, error_message=error_msg)

    def _is_valid_image_url(self, url: str) -> bool:
        """Validate image URL format
        
        Args:
            url: URL to validate
        
        Returns:
            bool: True if URL appears valid, False otherwise
        """
        if not url:
            return False
        
        # Basic HTTP(S) URL validation
        if not (url.startswith('http://') or url.startswith('https://')):
            return False
        
        # Check URL is not too long
        # if len(url) > 2048:
        #     return False
        
        return True

    def adlabels(self, payload: dict) -> dict:
        endpoint = f"{self.account_id}/adlabels"
        response = self._make_request("POST", endpoint, json_data=payload)
        adlabel_id = response.get("id")
        if adlabel_id:
            logger.info(f"✅ Ad label created successfully: {adlabel_id}")
            return {"success": True, "adlabel_id": adlabel_id, "raw_response": response}
        else:
            raise ValueError(f"No ad label ID in response: {response}")


    def create_ad(self, payload: Dict) -> PublishResult:
        """Create Meta ad"""
        endpoint = f"{self.account_id}/ads"

        logger.info(f"Creating ad on {endpoint}")

        try:
            if not payload:
                raise ValueError("Payload is required")
            if not payload.get('name'):
                raise ValueError("Ad name is required")
            if not payload.get('adset_id'):
                raise ValueError("Ad set ID is required")
            if not payload.get('creative'):
                raise ValueError("Creative is required")
            if not payload.get('creative', {}).get('creative_id'):
                raise ValueError("Creative ID is required in creative")

            response = self._make_request("POST", endpoint, json_data=payload)
            ad_id = response.get("id")

            if ad_id:
                logger.info(f"✅ Ad created successfully: {ad_id}")
                return PublishResult(
                    success=True,
                    ad_id=ad_id,
                    raw_response=response
                )
            else:
                raise ValueError(f"No ad ID in response: {response}")

        except ValueError as e:
            error_msg = str(e)
            logger.error(f"Ad creation validation failed: {error_msg}")
            
            frappe.log_error(
                title="Meta Ad Creation Validation Error",
                message=(
                    f"Error: {error_msg}\n"
                    f"Account ID: {self.account_id}\n"
                    f"Payload: {json.dumps(payload, indent=2, default=str)}"
                )
            )
            
            return PublishResult(success=False, error_message=error_msg)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Ad creation failed: {error_msg}")
            
            frappe.log_error(
                title="Meta Ad Creation Failed",
                message=(
                    f"Error: {error_msg}\n"
                    f"Account ID: {self.account_id}\n"
                    f"Payload: {json.dumps(payload, indent=2, default=str)}\n"
                    f"Traceback: {frappe.get_traceback()}"
                )
            )
            
            return PublishResult(success=False, error_message=error_msg)
        
    def create_audience(self, payload: dict) -> AudienceResult:
        url = f"{self.base_url}/{self.account_id}/customaudiences"
        response = requests.post(
            url,
            params={"access_token": self.access_token},
            json=payload
        )
        data = response.json()
        if "error" in data:
            return AudienceResult(success=False, error_message=data["error"]["message"])
        return AudienceResult(success=True, audience_id=data["id"])


    def add_users_to_audience(self, audience_id: str, schema: list, hashed_data: list) -> dict:
        url = f"{self.base_url}/{audience_id}/users"
        payload = {"payload": {"schema": schema, "data": hashed_data}}
        response = requests.post(
            url,
            params={"access_token": self.access_token},
            json=payload
        )
        return response.json()
    # Required abstract methods (minimal implementations)
    def fetch_account_analytics(self) -> AnalyticsResult:
        try:
            # Fetch account-level analytics from last 7 days
            # Only use valid fields from Meta API
            fields = ",".join([
                "spend",
                "impressions",
                "clicks",
                "ctr",
                "cpc",
                "reach",
                "frequency",
                "actions",
                "conversions",
                "purchase_roas",
                "cost_per_purchase"
            ])
            
            # Use date_preset instead of time_range - simpler and more reliable
            params = {
                "fields": fields,
                "date_preset": "last_7d"  # Meta API will aggregate last 7 days
            }
            
            logger.info(f"Fetching insights for account {self.account_id}")
            logger.info(f"Parameters: {params}")
            
            data = self._make_request(
                "GET",
                f"{self.account_id}/insights",
                params=params,
            )
            
            logger.info(f"Raw API Response: {json.dumps(data, indent=2, default=str)}")
            logger.info(f"Response type: {type(data)}")
            logger.info(f"Response keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
            
            # Handle the response structure
            if not isinstance(data, dict):
                logger.error(f"Response is not a dict, got {type(data)}: {str(data)[:200]}")
                return AnalyticsResult(success=False, error_message=f"Meta API returned unexpected type: {type(data)}")
            
            # Check for API errors
            if "error" in data:
                error_detail = data.get("error", {})
                if isinstance(error_detail, dict):
                    error_msg = error_detail.get("message", str(error_detail))
                else:
                    error_msg = str(error_detail)
                logger.error(f"Meta API Error: {error_msg}")
                return AnalyticsResult(success=False, error_message=f"Meta API returned error: {error_msg}")
            
            # Verify data array exists
            if "data" not in data:
                logger.error(f"Response missing 'data' key. Keys: {list(data.keys())}")
                return AnalyticsResult(
                    success=False, 
                    error_message=f"Invalid response format from Meta API. Expected 'data' array. Got: {list(data.keys())}"
                )
            
            data_array = data.get("data", [])
            
            # Check if data array is empty
            if not isinstance(data_array, list):
                logger.error(f"Data is not a list, got {type(data_array)}: {data_array}")
                return AnalyticsResult(success=False, error_message="Meta API returned invalid data structure")
            
            if len(data_array) == 0:
                logger.warning("Data array is empty - account may have no activity in last 7 days")
                return AnalyticsResult(
                    success=False, 
                    error_message="No analytics data found for the last 7 days. This account may not have any activity."
                )
            
            logger.info(f"Data array has {len(data_array)} items")
            
            # Aggregate metrics from all days (Meta might return multiple daily breakdowns)
            metrics = {
                "spend": 0.0,
                "impressions": 0,
                "clicks": 0,
                "ctr": 0.0,
                "cpc": 0.0,
                "reach": 0,
                "frequency": 0.0,
                "actions": 0,
                "conversions": 0,
                "cpc": 0.0,
                "action_rate": 0.0,
                "cost_per_action": 0.0,
                "conversion_rate": 0.0,
                "purchase_roas": 0.0,
                "cost_per_purchase": 0.0
            }
            
            # Helper function to safely convert string values from API
            def safe_int(val):
                """Convert API values to int, handling strings, dicts, lists, and None"""
                if val is None or val == "":
                    return 0
                
                # Handle dict with "value" key (Meta's action breakdown format)
                if isinstance(val, dict):
                    if "value" in val:
                        return safe_int(val["value"])  # Recursive call
                    logger.warning(f"Dict without 'value' key: {val}")
                    return 0
                
                # Handle list of dicts (Meta's breakdowns format)
                if isinstance(val, list):
                    if len(val) == 0:
                        return 0
                    # If list of dicts, sum their values
                    if isinstance(val[0], dict):
                        total = 0
                        for item in val:
                            if "value" in item:
                                total += safe_int(item["value"])
                        return total
                    # If list of strings/numbers, sum them
                    return sum(safe_int(v) for v in val)
                
                # Handle string numbers
                if isinstance(val, str):
                    try:
                        return int(val)
                    except (ValueError, TypeError):
                        logger.warning(f"Could not convert string to int: {val}")
                        return 0
                
                # Handle numeric types
                try:
                    return int(val) if val else 0
                except (ValueError, TypeError):
                    logger.warning(f"Could not convert value to int: {val} (type: {type(val)})")
                    return 0
            
            def safe_float(val):
                """Convert API values to float, handling strings, dicts, lists, and None"""
                if val is None or val == "":
                    return 0.0
                
                # Handle dict with "value" key
                if isinstance(val, dict):
                    if "value" in val:
                        return safe_float(val["value"])  # Recursive call
                    logger.warning(f"Dict without 'value' key: {val}")
                    return 0.0
                
                # Handle list of dicts
                if isinstance(val, list):
                    if len(val) == 0:
                        return 0.0
                    # If list of dicts, sum their values
                    if isinstance(val[0], dict):
                        total = 0.0
                        for item in val:
                            if "value" in item:
                                total += safe_float(item["value"])
                        return total
                    # If list of strings/numbers, sum them
                    return sum(safe_float(v) for v in val)
                
                # Handle string numbers
                if isinstance(val, str):
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        logger.warning(f"Could not convert string to float: {val}")
                        return 0.0
                
                # Handle numeric types
                try:
                    return float(val) if val else 0.0
                except (ValueError, TypeError):
                    logger.warning(f"Could not convert value to float: {val} (type: {type(val)})")
                    return 0.0
            
            for item in data_array:
                logger.debug(f"Processing item: {json.dumps(item, indent=2, default=str)}")
                
                metrics["spend"] += safe_float(item.get("spend"))
                metrics["impressions"] += safe_int(item.get("impressions"))
                metrics["clicks"] += safe_int(item.get("clicks"))
                metrics["reach"] += safe_int(item.get("reach"))
                metrics["actions"] += safe_int(item.get("actions"))
                metrics["conversions"] += safe_int(item.get("conversions"))
            
            logger.info(f"Aggregated metrics - Spend: {metrics['spend']}, Impressions: {metrics['impressions']}, Clicks: {metrics['clicks']}")
            
            # Calculate derived metrics
            if metrics["impressions"] > 0:
                metrics["ctr"] = round((metrics["clicks"] / metrics["impressions"]) * 100, 2)
            
            if metrics["clicks"] > 0:
                metrics["cpc"] = round(metrics["spend"] / metrics["clicks"], 2)
            
            if metrics["actions"] > 0:
                metrics["cost_per_action"] = round(metrics["spend"] / metrics["actions"], 2)
                metrics["action_rate"] = round((metrics["actions"] / metrics["impressions"]) * 100, 2) if metrics["impressions"] > 0 else 0
            
            if metrics["conversions"] > 0:
                metrics["cost_per_purchase"] = round(metrics["spend"] / metrics["conversions"], 2)
                metrics["conversion_rate"] = round((metrics["conversions"] / metrics["clicks"]) * 100, 2) if metrics["clicks"] > 0 else 0
            
            # Get frequency and ROAS from latest data (last item)
            latest_data = data_array[-1] if data_array else {}
            metrics["frequency"] = safe_float(latest_data.get("frequency"))
            metrics["purchase_roas"] = safe_float(latest_data.get("purchase_roas"))
            
            # Fetch campaign counts (with error handling - these are optional)
            try:
                campaigns_data = self._make_request(
                    "GET",
                    f"{self.account_id}/campaigns",
                    params={"fields": "id,status", "limit": 1}
                )
                
                total_campaigns = campaigns_data.get("paging", {}).get("cursors", {}).get("total_count", 0)
                active_campaigns = len([c for c in campaigns_data.get("data", []) if c.get("status") == "ACTIVE"])
                
                metrics["active_campaigns"] = active_campaigns
                metrics["total_campaigns"] = total_campaigns
                logger.info(f"Campaigns: {active_campaigns} active, {total_campaigns} total")
            except Exception as e:
                logger.warning(f"Could not fetch campaign counts: {str(e)}")
                metrics["active_campaigns"] = 0
                metrics["total_campaigns"] = 0
            
            # Fetch adsets count (optional)
            try:
                adsets_data = self._make_request(
                    "GET",
                    f"{self.account_id}/adsets",
                    params={"fields": "id", "limit": 1}
                )
                metrics["adsets_count"] = adsets_data.get("paging", {}).get("cursors", {}).get("total_count", 0)
                logger.info(f"Ad Sets count: {metrics['adsets_count']}")
            except Exception as e:
                logger.warning(f"Could not fetch ad sets count: {str(e)}")
                metrics["adsets_count"] = 0
            
            # Fetch ads count (optional)
            try:
                ads_data = self._make_request(
                    "GET",
                    f"{self.account_id}/ads",
                    params={"fields": "id", "limit": 1}
                )
                metrics["ads_count"] = ads_data.get("paging", {}).get("cursors", {}).get("total_count", 0)
                logger.info(f"Ads count: {metrics['ads_count']}")
            except Exception as e:
                logger.warning(f"Could not fetch ads count: {str(e)}")
                metrics["ads_count"] = 0
            
            logger.info(f"Analytics fetch completed. Final metrics: {json.dumps({k: v for k, v in metrics.items() if k in ['spend', 'impressions', 'clicks', 'reach', 'frequency']}, default=str)}")
            return AnalyticsResult(success=True, metrics=metrics)
        except Exception as e:
            logger.error(f"Error fetching account analytics: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return AnalyticsResult(success=False, error_message=str(e))

    def fetch_post_analytics(self, campaign_id: str) -> AnalyticsResult:
        try:
            data = self._make_request(
                "GET",
                f"{campaign_id}/insights",
                params={"date_preset": "last_7d", "fields": "impressions,spend"},
            )
            return AnalyticsResult(success=True, metrics=data.get("data", []))
        except Exception as e:
            return AnalyticsResult(success=False, error_message=str(e))

    def fetch_campaign_analytics(self, campaign_id: str) -> AnalyticsResult:
        """
        Fetch campaign-level analytics from Meta Ads API.
        
        Endpoint: GET /{campaign_id}/insights
        Reference: https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group/insights
        
        Args:
            campaign_id: The Meta campaign ID (without 'act_' prefix)
            
        Returns:
            AnalyticsResult with success status and aggregated metrics
        """
        try:
            logger.info(f"Fetching analytics for campaign: {campaign_id}")
            
            # Define ONLY fields that Meta API accepts for campaign/ads insights
            # These are the ONLY valid fields - do NOT include calculated metrics
            # Reference: https://developers.facebook.com/docs/marketing-api/reference/ads-insights/
            fields = ",".join([
                "spend",                      # Total spend
                "impressions",                # Number of impressions
                "clicks",                     # All clicks
                "ctr",                        # Click-through rate (calculated by API, safe to request)
                "cpc",                        # Cost per click (calculated by API, safe to request)
                "reach",                      # Unique reach
                "frequency",                  # Average frequency
                "actions",                    # Total actions
                "conversions",                # Total conversions
                "cost_per_conversion",        # Cost per conversion (calculated by API, safe to request)
                "purchase_roas",              # Return on ad spend (purchases)
                "inline_link_clicks",         # Link clicks
                "outbound_clicks_unique",     # Unique outbound clicks
                "video_10_sec_watched_actions",  # Video watches (10 sec)
            ])
            
            # Fetch insights for the last 7 days with aggregation
            params = {
                "fields": fields,
                "date_preset": "last_7d",  # Aggregate last 7 days
                "time_increment": 1        # Return one aggregated row
            }
            
            logger.info(f"Fetching campaign insights from Meta API for campaign {campaign_id}")
            logger.debug(f"Request fields: {fields}")
            
            data = self._make_request(
                "GET",
                f"{campaign_id}/insights",
                params=params
            )
            
            if "error" in data:
                error_detail = data.get("error", {})
                if isinstance(error_detail, dict):
                    error_msg = error_detail.get("message", str(error_detail))
                else:
                    error_msg = str(error_detail)
                logger.error(f"Campaign analytics API error: {error_msg}")
                return AnalyticsResult(success=False, error_message=error_msg)
            
            # Process data array
            data_array = data.get("data", [])
            if not data_array:
                logger.warning(f"No analytics data available for campaign {campaign_id} yet")
                return AnalyticsResult(
                    success=False,
                    error_message=f"No analytics data available for campaign {campaign_id}. Campaign may be too new or have no activity."
                )
            
            logger.info(f"Received {len(data_array)} data items from Meta API")
            
            # Initialize metrics dictionary with default values
            metrics = {
                "spend": 0.0,
                "impressions": 0,
                "clicks": 0,
                "ctr": 0.0,
                "cpc": 0.0,
                "reach": 0,
                "frequency": 0.0,
                "actions": 0,
                "action_rate": 0.0,
                "cost_per_action": 0.0,
                "conversions": 0,
                "conversion_rate": 0.0,
                "cost_per_conversion": 0.0,
                "purchase_roas": 0.0,
                "video_views": 0,
                "inline_link_clicks": 0,
                "outbound_clicks": 0
            }
            
            # Aggregate metrics from all items (usually single row when date_preset is used)
            for item in data_array:
                logger.debug(f"Processing API response item: {json.dumps(item, indent=2, default=str)}")
                
                metrics["spend"] += safe_float(item.get("spend"))
                metrics["impressions"] += safe_int(item.get("impressions"))
                metrics["clicks"] += safe_int(item.get("clicks"))
                metrics["ctr"] = safe_float(item.get("ctr"))  # Already calculated by API
                metrics["cpc"] = safe_float(item.get("cpc"))  # Already calculated by API
                metrics["reach"] += safe_int(item.get("reach"))
                metrics["frequency"] = safe_float(item.get("frequency"))
                metrics["actions"] += safe_int(item.get("actions"))
                metrics["conversions"] += safe_int(item.get("conversions"))
                metrics["cost_per_conversion"] = safe_float(item.get("cost_per_conversion"))
                metrics["purchase_roas"] = safe_float(item.get("purchase_roas"))
                metrics["video_views"] += safe_int(item.get("video_10_sec_watched_actions"))
                metrics["inline_link_clicks"] += safe_int(item.get("inline_link_clicks"))
                metrics["outbound_clicks"] += safe_int(item.get("outbound_clicks_unique"))
            
            logger.info(f"Aggregated analytics - Spend: {metrics['spend']}, Impressions: {metrics['impressions']}, Clicks: {metrics['clicks']}, Conversions: {metrics['conversions']}")
            
            # Calculate derived metrics LOCALLY (not from API)
            if metrics["actions"] > 0 and metrics["impressions"] > 0:
                metrics["action_rate"] = round((metrics["actions"] / metrics["impressions"]) * 100, 2)
            
            if metrics["conversions"] > 0 and metrics["clicks"] > 0:
                metrics["conversion_rate"] = round((metrics["conversions"] / metrics["clicks"]) * 100, 2)
            
            if metrics["actions"] > 0:
                metrics["cost_per_action"] = round(metrics["spend"] / metrics["actions"], 2)
            
            logger.info(f"Campaign analytics fetched successfully")
            logger.debug(f"Final metrics: {json.dumps(metrics, default=str)}")
            
            return AnalyticsResult(success=True, metrics=metrics)
        
        except Exception as e:
            error_msg = f"Error fetching campaign analytics: {str(e)}"
            logger.error(error_msg)
            import traceback
            logger.error(traceback.format_exc())
            return AnalyticsResult(success=False, error_message=error_msg)

    def fetch_adset_analytics(self, adset_id: str) -> AnalyticsResult:
        """
        Fetch ad set-level analytics from Meta Ads API.
        
        Endpoint: GET /{adset_id}/insights
        Reference: https://developers.facebook.com/docs/marketing-api/reference/ad-set/insights
        
        Args:
            adset_id: The Meta ad set ID
            
        Returns:
            AnalyticsResult with success status and aggregated metrics
        """
        try:
            logger.info(f"Fetching analytics for ad set: {adset_id}")
            
            # Define ONLY fields that Meta API accepts for adset insights
            # Same as campaign-level analytics
            fields = ",".join([
                "spend",                      # Total spend
                "impressions",                # Number of impressions
                "clicks",                     # All clicks
                "ctr",                        # Click-through rate (calculated by API, safe to request)
                "cpc",                        # Cost per click (calculated by API, safe to request)
                "reach",                      # Unique reach
                "frequency",                  # Average frequency
                "actions",                    # Total actions
                "conversions",                # Total conversions
                "cost_per_conversion",        # Cost per conversion (calculated by API, safe to request)
                "purchase_roas",              # Return on ad spend (purchases)
                "inline_link_clicks",         # Link clicks
                "outbound_clicks_unique",     # Unique outbound clicks
                "video_10_sec_watched_actions",  # Video watches (10 sec)
            ])
            
            # Fetch insights for the last 7 days with aggregation
            params = {
                "fields": fields,
                "date_preset": "last_7d",  # Aggregate last 7 days
                "time_increment": 1        # Return one aggregated row
            }
            
            logger.info(f"Fetching ad set insights from Meta API for adset {adset_id}")
            logger.debug(f"Request fields: {fields}")
            
            data = self._make_request(
                "GET",
                f"{adset_id}/insights",
                params=params
            )
            
            if "error" in data:
                error_detail = data.get("error", {})
                if isinstance(error_detail, dict):
                    error_msg = error_detail.get("message", str(error_detail))
                else:
                    error_msg = str(error_detail)
                logger.error(f"Ad set analytics API error: {error_msg}")
                return AnalyticsResult(success=False, error_message=error_msg)
            
            # Process data array
            data_array = data.get("data", [])
            if not data_array:
                logger.warning(f"No analytics data available for ad set {adset_id} yet")
                return AnalyticsResult(
                    success=False,
                    error_message=f"No analytics data available for ad set {adset_id}. Ad set may be too new or have no activity."
                )
            
            logger.info(f"Received {len(data_array)} data items from Meta API")
            
            # Initialize metrics dictionary with default values
            metrics = {
                "spend": 0.0,
                "impressions": 0,
                "clicks": 0,
                "ctr": 0.0,
                "cpc": 0.0,
                "reach": 0,
                "frequency": 0.0,
                "actions": 0,
                "action_rate": 0.0,
                "cost_per_action": 0.0,
                "conversions": 0,
                "conversion_rate": 0.0,
                "cost_per_conversion": 0.0,
                "purchase_roas": 0.0,
                "video_views": 0,
                "inline_link_clicks": 0,
                "outbound_clicks": 0
            }
            
            # Aggregate metrics from all items (usually single row when date_preset is used)
            for item in data_array:
                logger.debug(f"Processing API response item: {json.dumps(item, indent=2, default=str)}")
                
                metrics["spend"] += safe_float(item.get("spend"))
                metrics["impressions"] += safe_int(item.get("impressions"))
                metrics["clicks"] += safe_int(item.get("clicks"))
                metrics["ctr"] = safe_float(item.get("ctr"))  # Already calculated by API
                metrics["cpc"] = safe_float(item.get("cpc"))  # Already calculated by API
                metrics["reach"] += safe_int(item.get("reach"))
                metrics["frequency"] = safe_float(item.get("frequency"))
                metrics["actions"] += safe_int(item.get("actions"))
                metrics["conversions"] += safe_int(item.get("conversions"))
                metrics["cost_per_conversion"] = safe_float(item.get("cost_per_conversion"))
                metrics["purchase_roas"] = safe_float(item.get("purchase_roas"))
                metrics["video_views"] += safe_int(item.get("video_10_sec_watched_actions"))
                metrics["inline_link_clicks"] += safe_int(item.get("inline_link_clicks"))
                metrics["outbound_clicks"] += safe_int(item.get("outbound_clicks_unique"))
            
            logger.info(f"Aggregated analytics - Spend: {metrics['spend']}, Impressions: {metrics['impressions']}, Clicks: {metrics['clicks']}, Conversions: {metrics['conversions']}")
            
            # Calculate derived metrics LOCALLY (not from API)
            if metrics["actions"] > 0 and metrics["impressions"] > 0:
                metrics["action_rate"] = round((metrics["actions"] / metrics["impressions"]) * 100, 2)
            
            if metrics["conversions"] > 0 and metrics["clicks"] > 0:
                metrics["conversion_rate"] = round((metrics["conversions"] / metrics["clicks"]) * 100, 2)
            
            if metrics["actions"] > 0:
                metrics["cost_per_action"] = round(metrics["spend"] / metrics["actions"], 2)
            
            logger.info(f"Ad set analytics fetched successfully")
            logger.debug(f"Final metrics: {json.dumps(metrics, default=str)}")
            
            return AnalyticsResult(success=True, metrics=metrics)
        
        except Exception as e:
            error_msg = f"Error fetching ad set analytics: {str(e)}"
            logger.error(error_msg)
            import traceback
            logger.error(traceback.format_exc())
            return AnalyticsResult(success=False, error_message=error_msg)

    def get_daily_limit(self) -> int:
        return self.DAILY_API_LIMIT

    def refresh_token(self, integration_name: str = None) -> TokenRefreshResult:
        return TokenRefreshResult(success=False, error_message="Not implemented")

    def validate_credentials(self) -> Dict:
        try:
            data = self._make_request("GET", self.account_id, params={"fields": "name,account_status"})
            return {"success": True, "account_name": data.get("name")}
        except Exception as e:
            return {"success": False, "error": str(e)}
