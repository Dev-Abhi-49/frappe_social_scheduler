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
                if json_data and method.upper() == "POST":
                    logger.debug(f"Sending POST request to {endpoint}")
                    logger.debug(f"Payload size: {len(json.dumps(json_data))} bytes")
                    
                    # Log full payload for adcreatives endpoint for debugging
                    if "adcreatives" in endpoint:
                        logger.info(f"AdCreatives payload: {json.dumps(json_data, indent=2)}")
                
                response = requests.request(method.upper(), url, **kwargs)
                response.raise_for_status()
                data = response.json()

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
        
    # Required abstract methods (minimal implementations)
    def fetch_account_analytics(self) -> AnalyticsResult:
        try:
            data = self._make_request(
                "GET",
                f"{self.account_id}/insights",
                params={"date_preset": "last_7d", "fields": "impressions,spend"},
            )
            return AnalyticsResult(success=True, metrics=data.get("data", []))
        except Exception as e:
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
