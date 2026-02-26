"""
Meta Ads Provider - Direct calls to Meta Graph API (no SDK)
Handles Facebook and Instagram ad operations through Meta Graph API
"""

import requests
import frappe
import json
import logging
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


class MetaAdsProvider(BaseProvider):
    PLATFORM = "Meta"
    MAX_BUDGET = 100000
    SUPPORTS_IMAGES = True
    SUPPORTS_VIDEO = True
    DAILY_API_LIMIT = 200

    def __init__(self, integration_name: str = None):
        super().__init__(integration_name)
        try:
            self.api_version = self.settings.meta_api_version or "v24.0"
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
                        1885183: "Invalid image URL - URL may contain unsupported parameters or be inaccessible. Try removing tracking parameters.",
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
        """Create Meta campaign - payload should be pre-validated and mapped by caller"""
        endpoint = f"{self.account_id}/campaigns"

        logger.info(f"Creating campaign on {endpoint}")

        try:
            if not payload:
                raise ValueError("Payload is required")
            if not payload.get('name'):
                raise ValueError("Campaign name is required")

            response = self._make_request("POST", endpoint, json_data=payload)
            campaign_id = response.get("id")

            if campaign_id:
                logger.info(f"✅ Campaign created: {campaign_id}")
                return PublishResult(success=True, campaign_id=campaign_id, raw_response=response)
            else:
                raise ValueError(f"No campaign ID in response: {response}")

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

    def create_ad_set(self, payload: Dict) -> PublishResult:
        """Create Meta ad set - payload should be pre-validated and mapped by caller"""
        endpoint = f"{self.account_id}/adsets"

        logger.info(f"Creating ad set on {endpoint}")

        try:
            if not payload:
                raise ValueError("Payload is required")
            if not payload.get('name'):
                raise ValueError("Ad set name is required")
            if not payload.get('campaign_id'):
                raise ValueError("Campaign ID is required")
            if not payload.get('daily_budget'):
                raise ValueError("Daily budget is required")

            response = self._make_request("POST", endpoint, json_data=payload)
            adset_id = response.get("id")

            if adset_id:
                logger.info(f"✅ Ad Set created: {adset_id}")
                return PublishResult(success=True, adset_id=adset_id, raw_response=response)
            else:
                raise ValueError(f"No ad set ID in response: {response}")

        except ValueError as e:
            error_msg = str(e)
            logger.error(f"Ad set creation validation failed: {error_msg}")
            frappe.log_error(
                title="Meta Ad Set Creation Validation Error",
                message=(
                    f"Error: {error_msg}\n"
                    f"Account ID: {self.account_id}\n"
                    f"Payload: {json.dumps(payload, indent=2, default=str)}"
                ),
            )
            return PublishResult(success=False, error_message=error_msg)
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Ad Set creation FAILED: {error_msg}")
            frappe.log_error(
                title="Meta Ad Set Creation Failed",
                message=(
                    f"Error: {error_msg}\n"
                    f"Account ID: {self.account_id}\n"
                    f"Payload: {json.dumps(payload, indent=2, default=str)}\n"
                    f"Traceback: {frappe.get_traceback()}"
                ),
            )
            return PublishResult(success=False, error_message=error_msg)

    def upload_image(self, payload: Dict) -> PublishResult:
        """Upload image to Meta and return URL"""
        endpoint = f"{self.account_id}/adimages"

        filename = payload.get("filename")
        if not filename:
            raise ValueError("Filename is required for image upload")

        logger.info(f"Uploading image: {filename}")

        try:
            with open(filename, "rb") as f:
                files = {"file": f}
                response = self._make_request("POST", endpoint, files=files)

            if "images" in response:
                image_data = response["images"]
                # Get first image data from response
                first_image = list(image_data.values())[0]

                # Get the URL instead of hash
                image_url = first_image.get("url")  # This is the actual image URL
                image_hash = first_image.get("hash")  # Keep hash for reference

                if image_url:
                    logger.info(f"✅ Image uploaded successfully: {image_url}")
                    return PublishResult(
                        success=True,
                        image_hash=image_hash,
                        image_url=image_url,  # Return URL in campaign_id field
                        raw_response=response
                    )
                else:
                    raise ValueError("No image URL in response")
            else:
                raise ValueError(f"Image upload failed: {response}")

        except FileNotFoundError:
            error_msg = f"File not found: {filename}"
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
    
    def create_creative(self, payload: Dict, page_access_token: str = None) -> PublishResult:
        """Create Meta ad creative
        
        Args:
            payload: Creative payload with object_story_spec
            page_access_token: Page access token (not used for API call, only for reference)
        
        Returns:
            PublishResult with success status and creative_id or error_message
        """
        endpoint = f"{self.account_id}/adcreatives"

        logger.info(f"Creating creative on endpoint: {endpoint}")

        try:
            # Validate payload structure
            if not payload:
                raise ValueError("Payload is required")
            
            if not payload.get('name'):
                raise ValueError("'name' field is required in creative payload")
            
            if not payload.get('object_story_spec'):
                raise ValueError("'object_story_spec' is required in creative payload")
            
            story_spec = payload['object_story_spec']
            if not story_spec.get('page_id'):
                raise ValueError("'page_id' is required in object_story_spec")
            
            if not story_spec.get('link_data'):
                raise ValueError("'link_data' is required in object_story_spec")
            
            # Validate link_data structure
            link_data = story_spec['link_data']
            if not isinstance(link_data, dict):
                raise ValueError("'link_data' must be an object/dictionary")
            
            # Ensure link_data has required fields
            if 'description' not in link_data:
                link_data['description'] = ''
            
            if 'link' not in link_data:
                link_data['link'] = ''
            
            # Log detailed payload info for debugging
            logger.info(f"Creative payload structure validated")
            logger.info(f"Name: {payload.get('name')}")
            logger.info(f"Page ID: {story_spec.get('page_id')}")
            logger.info(f"Link data keys: {list(link_data.keys())}")
            if link_data.get('picture'):
                logger.info(f"Image URL present (length: {len(link_data['picture'])} chars)")
            
            # Validate image URLs in link_data if present
            if link_data.get('picture'):
                if not self._is_valid_image_url(link_data['picture']):
                    logger.warning(f"Image URL validation warning - URL may be invalid: {link_data['picture'][:100]}...")
            
            # Validate child attachments if present
            if link_data.get('child_attachments'):
                for idx, attachment in enumerate(link_data['child_attachments']):
                    if attachment.get('picture'):
                        if not self._is_valid_image_url(attachment['picture']):
                            logger.warning(f"Carousel image {idx} URL may be invalid")
            
            logger.info(f"Sending creative creation request to Meta API...")
            
            # Always use account access token for creative creation
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
