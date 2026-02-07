"""
OAuth API Endpoints for Ads Manager
Meta (Facebook / Instagram Ads) OAuth

Handles OAuth flows for connecting ad platforms including:
- Facebook Ads
- Instagram Ads

Features:
- Secure state validation
- Token exchange and refresh
- Account selection and connection
- Page access token storage
- Comprehensive error handling and logging
"""

import frappe
import secrets
import requests
import logging
from frappe import _
from frappe.utils import get_url, now_datetime, add_to_date
from urllib.parse import quote as quoted
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from frappe_social.ads_manager.providers import get_provider

logger = logging.getLogger(__name__)

# Constants
OAUTH_STATE_CACHE_TTL = 300  # 5 minutes
SESSION_CACHE_TTL = 600  # 10 minutes
REQUEST_TIMEOUT = 30  # seconds
MAX_RETRIES = 3
BACKOFF_FACTOR = 0.3

settings = frappe.get_single("Social Settings")
api_version = settings.meta_api_version or "v24.0"


# ======================================================================
# OAuth Initiation
# ======================================================================


@frappe.whitelist()
def initiate_oauth(
    platform: str,
    account_name: str = None,
    account_description: str = None,
    organization: str = None,
) -> dict:
    """Initiate OAuth flow for the specified platform."""
    try:
        if not platform or not isinstance(platform, str):
            frappe.throw(_("Platform is required"))

        # Prepare cache data
        cache_data = {
            "platform": platform,
            "account_name": account_name,
            "account_description": account_description,
            "organization": organization,
            "user": frappe.session.user,
        }

        state = secrets.token_urlsafe(32)
        redirect_uri = get_callback_url(platform)
        auth_url = _get_meta_auth_url(platform, settings, redirect_uri, state)

        # Store state in cache with TTL
        frappe.cache().set_value(f"ads_oauth_state_{state}", cache_data, expires_in_sec=OAUTH_STATE_CACHE_TTL)

        return {
            "authorization_url": auth_url,
            "state": state,
        }

    except Exception:
        frappe.throw(_("Failed to initiate Authentication. Please try again."))


def get_callback_url(platform: str) -> str:
    """Generate callback URL"""
    return f"{get_url()}/api/method/frappe_social.ads_manager.api.oauth.callback_{platform.lower()}"


def _get_meta_auth_url(platform: str, settings, redirect_uri: str, state: str) -> str:
    """Generate Meta OAuth URL"""
    if platform in ["Facebook", "Instagram"]:
        scopes = [
            "pages_show_list",
            "pages_read_engagement",
            "pages_manage_posts",
            "pages_read_user_content",
            "business_management",
            "email",
            "public_profile",
            "ads_management",
            "ads_read",
        ]

        if platform == "Instagram":
            scopes.extend(["instagram_basic", "instagram_content_publish", "instagram_manage_insights"])

        params = {
            "client_id": settings.meta_app_id,
            "redirect_uri": redirect_uri,
            "scope": ",".join(scopes),
            "response_type": "code",
            "state": state,
        }
        return f"https://www.facebook.com/{api_version}/dialog/oauth?{'&'.join(f'{k}={quoted(str(v))}' for k, v in params.items())}"

    frappe.throw(_(f"Unsupported platform: {platform}"))


# =============================================================================
# OAuth Callback
# =============================================================================
@frappe.whitelist(allow_guest=True)
def callback_facebook():
    """Facebook OAuth callback"""
    return _handle_mata_callback("Facebook")


def _handle_mata_callback(platform: str):
    """Handle Meta OAuth callback."""
    try:
        # Extract callback parameters
        code = frappe.request.args.get("code")
        state = frappe.request.args.get("state")
        error = frappe.request.args.get("error")

        # Handle OAuth errors
        if error:
            return _oauth_error_redirect(f"{platform}: {error}")

        # Validate state to prevent CSRF attacks
        cache_data = frappe.cache().get_value(f"ads_oauth_state_{state}")
        if not cache_data or cache_data.get("platform") != platform:
            return _oauth_error_redirect("OAuth state expired or invalid")

        short_token = (
            requests.get(
                f"https://graph.facebook.com/{api_version}/oauth/access_token",
                params={
                    "client_id": settings.meta_app_id,
                    "client_secret": settings.get_password("meta_app_secret"),
                    "redirect_uri": get_callback_url(platform),
                    "code": code,
                },
            )
            .json()
            .get("access_token")
        )

        if not short_token:
            return _oauth_error_redirect("Failed to obtain access token")

        long_token_data = requests.get(
            f"https://graph.facebook.com/{api_version}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.meta_app_id,
                "client_secret": settings.get_password("meta_app_secret"),
                "fb_exchange_token": short_token,
            },
        ).json()

        # Exchange for long-lived token
        user_token = long_token_data.get("access_token", short_token)
        expires_in = long_token_data.get("expires_in", 5184000)

        me_data = requests.get(
            f"https://graph.facebook.com/{api_version}/me",
            params={"access_token": user_token, "fields": "id,name,email"},
        ).json()

        # Fetch pages WITH their access tokens
        pages = (
            requests.get(
                f"https://graph.facebook.com/{api_version}/me/accounts",
                params={
                    "access_token": user_token, 
                    "fields": "id,name,access_token,picture{url},fan_count"  # Include access_token!
                },
            )
            .json()
            .get("data", [])
        )

        if not pages:
            return _oauth_error_redirect("No Pages Found")

        ad_accounts = (
            requests.get(
                f"https://graph.facebook.com/{api_version}/me/adaccounts",
                params={
                    "access_token": user_token,
                    "fields": "id,name,account_status,currency,timezone_name,amount_spent,account_id",
                    "limit": 100,
                },
            )
            .json()
            .get("data", [])
        )

        if not ad_accounts:
            return _oauth_error_redirect("No ad accounts found for this user")

        # Store session data
        session_key = secrets.token_urlsafe(32)
        session_data = {
            "platform": platform,
            "user": cache_data["user"],
            "user_access_token": user_token,
            "expires_in": expires_in,
            "pages": pages,  # This now includes access_token for each page
            "ad_accounts": ad_accounts,
            "auth_user_id": me_data.get("id"),
            "auth_user_name": me_data.get("name"),
            "account_name": cache_data.get("account_name"),
            "account_description": cache_data.get("account_description"),
            "organization": cache_data.get("organization"),
        }

        frappe.cache().set_value(f"meta_ads_{session_key}", session_data, expires_in_sec=SESSION_CACHE_TTL)
        frappe.cache().delete_value(f"ads_oauth_state_{state}")

        # If single account, connect directly
        if len(ad_accounts) == 1:
            try:
                result = _connect_ad_account(session_key, 0)
                location = _oauth_success_redirect(result.name)
                frappe.local.response.update({"type": "redirect", "location": location})
                return location
            except Exception as e:
                logger.error(f"Failed to auto-connect single account: {str(e)}")
                return _oauth_error_redirect("Failed to connect account automatically")

        # Multiple accounts - redirect to selection page
        location = f"/select-ads-account?session={quoted(session_key)}&platform={quoted(platform)}"
        frappe.local.response.update(
            {
                "type": "redirect",
                "location": location,
            }
        )
        return location
    except requests.RequestException as e:
        logger.error(f"Network error during OAuth callback: {str(e)}")
        return _oauth_error_redirect("Network error. Please try again.")
    except Exception as e:
        logger.error(f"Unexpected error in OAuth callback: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "OAuth Callback Error")
        return _oauth_error_redirect("An unexpected error occurred. Please try again.")


# =============================================================================
# Ad Account Selection
# =============================================================================


@frappe.whitelist()
def get_available_ad_accounts(session_key: str) -> dict:
    """
    Retrieve ad accounts from session cache for selection UI.

    """
    try:
        # Validate session key
        if not session_key or not isinstance(session_key, str) or len(session_key) < 20:
            frappe.throw(_("Invalid session key"))

        # Retrieve session data
        cache_data = frappe.cache().get_value(f"meta_ads_{session_key}")
        if not cache_data:
            frappe.throw(_("Session expired. Please reinitiate OAuth flow."))

        # Verify user context
        if cache_data.get("user") != frappe.session.user:
            logger.warning(
                f"Session user mismatch: expected {cache_data.get('user')}, got {frappe.session.user}"
            )
            frappe.throw(_("Session invalid for current user"))

        platform = cache_data.get("platform", "")
        ad_accounts = cache_data.get("ad_accounts", [])

        # Format accounts for UI
        formatted = []
        for i, acct in enumerate(ad_accounts):
            formatted.append(
                {
                    "index": i,
                    "id": acct.get("id", ""),
                    "account_id": acct.get("account_id", ""),
                    "name": acct.get("name", "Unknown"),
                    "currency": acct.get("currency", "N/A"),
                    "timezone": acct.get("timezone_name", "N/A"),
                    "status": acct.get("account_status", "N/A"),
                    "amount_spent": acct.get("amount_spent", 0),
                    "balance": acct.get("balance", 0),
                }
            )

        logger.info(f"Retrieved {len(formatted)} ad account(s) for session {session_key[:10]}...")

        return {
            "platform": platform,
            "ad_accounts": formatted,
            "authorized_by": cache_data.get("auth_user_name", "Unknown"),
            "account_count": len(formatted),
        }

    except frappe.ValidationError:
        raise
    except Exception as e:
        logger.error(f"Failed to get available ad accounts: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Get Ad Accounts Error")
        frappe.throw(_("Failed to retrieve ad accounts. Please try again."))


@frappe.whitelist()
def connect_ad_account(session_key: str, index: int):
    """Connect a specific ad account from selection."""
    return _connect_ad_account(session_key, int(index))


def _connect_ad_account(session_key: str, index: int):
    """
    Internal function to connect a specific ad account.

    Args:
        session_key: Session key from OAuth callback
        index: Index of account in session data

    Returns:
        Integration document
    """
    # Retrieve session data
    cache_data = frappe.cache().get_value(f"meta_ads_{session_key}")
    if not cache_data:
        frappe.throw(_("Session expired"))

    # Set user context for this operation
    user = cache_data.get("user")
    if user:
        frappe.set_user(user)

    # Validate account index
    ad_accounts = cache_data.get("ad_accounts", [])
    if not isinstance(index, int) or index < 0 or index >= len(ad_accounts):
        frappe.throw(_("Invalid account selection"))

    acct = ad_accounts[index]
    platform = cache_data["platform"]

    # Save integration
    integration = _save_ads_integration(
        platform=platform,
        account_name=cache_data.get("account_name"),
        ads_account_name=acct.get("name"),
        account_description=cache_data.get("account_description"),
        organization=cache_data.get("organization"),
        account_status=acct.get("account_status"),
        access_token=cache_data["user_access_token"],
        ad_account_id=acct.get("id"),
        ad_id=acct.get("account_id"),
        balance=acct.get("balance"),
        currency=acct.get("currency"),
        timezone=acct.get("timezone_name"),
        amount_spent=acct.get("amount_spent"),
        expires_in=cache_data["expires_in"],
        auth_user_id=cache_data.get("auth_user_id"),
        auth_user_name=cache_data.get("auth_user_name"),
        auth_user_email=cache_data.get("ads_data", {}).get("email"),
        pages_data=cache_data.get("pages", []),  # Pass pages with tokens
    )

    return integration


def _save_ads_integration(
    platform: str,
    ad_account_id: str,
    ad_id: str,
    account_name: str,
    ads_account_name: str,
    access_token: str,
    expires_in: int = None,
    account_description: str = None,
    organization: str = None,
    currency: str = None,
    balance: float = None,
    timezone: str = None,
    account_status: str = None,
    amount_spent: float = None,
    refresh_token: str = None,
    auth_user_id: str = None,
    auth_user_name: str = None,
    auth_user_email: str = None,
    pages_data: list = None,
) -> dict:
    """
    Create or update Ads Account Integration document.
    Now stores page access tokens in Facebook Pages child table.
    """
    try:
        # Check if integration already exists
        existing = frappe.db.get_value(
            "Ads Account Integration",
            {"platform": platform, "ad_account_id": ad_account_id},
        )

        if existing:
            integration = frappe.get_doc("Ads Account Integration", existing)
            is_new = False
        else:
            integration = frappe.new_doc("Ads Account Integration")
            integration.platform = platform
            integration.ad_account_id = ad_account_id
            integration.ad_id = ad_id
            integration.ads_account_name = ads_account_name
            is_new = True

        # Update main fields
        integration.account_name = account_name
        integration.connection_status = "Connected"
        integration.enabled = 1
        integration.last_error = None
        integration.authorization_date = now_datetime()

        if account_description:
            integration.account_description = account_description
        if organization:
            integration.organization = organization
        if currency:
            integration.currency = currency
        if timezone:
            integration.timezone = timezone
        if account_status is not None:
            integration.account_status = str(account_status)
        if amount_spent is not None:
            integration.amount_spent = float(amount_spent)
        if balance is not None:
            integration.balance = float(balance)

        # OAuth tokens
        integration.access_token = access_token
        if refresh_token:
            integration.refresh_token = refresh_token
        if expires_in:
            integration.token_expiry = add_to_date(now_datetime(), seconds=expires_in)

        # Authorized user info
        if auth_user_id:
            integration.authorized_user_id = auth_user_id
        if auth_user_name:
            integration.authorized_user_name = auth_user_name
        if auth_user_email:
            integration.authorized_user_email = auth_user_email

        # === STORE FACEBOOK PAGES WITH ACCESS TOKENS ===
        if pages_data:
            # Clear existing pages to avoid duplicates on reconnect
            integration.fb_pages = []
            
            for page in pages_data:
                page_id = page.get("id")
                page_name = page.get("name")
                page_access_token = page.get("access_token")  # CRITICAL: Get page token
                                               
                # Append page with its access token
                integration.append(
                    "fb_pages",
                    {
                        "page_id": page_id,
                        "page_name": page_name,
                        "page_access_token": page_access_token,  # STORE PAGE TOKEN!
                    }
                )
            
            logger.info(f"Stored {len(pages_data)} Facebook pages with access tokens")

        # Save everything (main doc + child table)
        integration.save(ignore_permissions=True)
        frappe.db.commit()

        # Clear cache
        frappe.clear_document_cache("Ads Account Integration", integration.name)

        action = "created" if is_new else "updated"
        logger.info(f"Integration {integration.name} {action} for {platform} account {ad_account_id}")

        return integration

    except frappe.DuplicateEntryError:
        logger.error(f"Duplicate integration for {platform} account {ad_account_id}")
        frappe.throw(_("An integration for this account already exists"))
    except Exception as e:
        logger.error(f"Failed to save integration: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Save Integration Error")
        frappe.throw(_("Failed to save integration. Please try again."))


@frappe.whitelist()
def disconnect(integration: str) -> dict:
    """Disconnect an ad account integration."""
    try:
        doc = frappe.get_doc("Ads Account Integration", integration)

        # Clear sensitive data
        doc.connection_status = "Not Connected"
        doc.access_token = None
        doc.refresh_token = None
        doc.page_access_token = None
        doc.enabled = 0
        doc.disconnected_at = now_datetime()

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        logger.info(f"Integration {integration} disconnected by user {frappe.session.user}")

        return {"success": True, "message": _("Integration disconnected successfully")}

    except frappe.ValidationError:
        raise
    except Exception as e:
        logger.error(f"Failed to disconnect integration {integration}: {str(e)}")
        frappe.log_error(frappe.get_traceback(), "Disconnect Integration Error")
        frappe.throw(_("Failed to disconnect integration. Please try again."))
        
@frappe.whitelist()
def test_connection(integration: str) -> dict:
    """Test if integration's connection is valid"""
    doc = frappe.get_doc("Ads Account Integration", integration)
    settings = frappe.get_single("Ads Setting")
    try:
        if doc.platform == "Facebook":
            # Use the user's access token from the main document to test connection
            token = doc.get_password("access_token")
            if not token:
                frappe.throw(_("Access token not found. Please reconnect the account."))
            
            valid = (
                requests.get(
                    f"https://graph.facebook.com/{settings.meta_api_version or 'v24.0'}/me",
                    params={"access_token": token},
                ).status_code
                == 200
            )
        else:
            valid = False
            
        doc.connection_status = "Connected" if valid else "Error"
        doc.save(ignore_permissions=True)
        return {"valid": valid}
    except Exception as e:
        doc.connection_status = "Error"
        doc.last_error = str(e)
        doc.save(ignore_permissions=True)
        return {"valid": False, "reason": str(e)}

# =============================================================================
# Redirect Helpers
# =============================================================================

@frappe.whitelist()
def finalize_ad_account_connection(session_key: str):
    frappe.cache().delete_value(f"meta_ads_{session_key}")
    return {"status": "done"}

def _oauth_error_redirect(message: str):
    """Redirect to error page"""
    location = f"/app/ads-account-integration?error={quoted(message)}"
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = location
    return location


def _oauth_success_redirect(integration_name: str):
    """Redirect to success page"""
    location = f"/app/ads-account-integration/{integration_name}"
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = location
    return location