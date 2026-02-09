"""
OAuth API Endpoints for Frappe Social Media Scheduler

Handles OAuth flow for all platforms:
- Facebook/Instagram (Meta Graph API)
- LinkedIn, Twitter, YouTube
"""

import frappe
import secrets
import hashlib
import base64
import requests
from frappe import _
from frappe.utils import get_url, now_datetime, add_to_date


# =============================================================================
# OAuth Initiation
# =============================================================================

settings = frappe.get_single("Social Settings")
api_version = settings.meta_api_version or "v24.0"


@frappe.whitelist()
def initiate_oauth(
    platform: str, account_name: str = None, account_description: str = None, organization: str = None
) -> dict:
    """Start OAuth flow for a platform"""
    state = secrets.token_urlsafe(32)
    cache_data = {
        "platform": platform,
        "account_name": account_name,
        "account_description": account_description,
        "organization": organization,
        "user": frappe.session.user,
    }
    redirect_uri = get_callback_url(platform)
    auth_url = _get_auth_url(platform, settings, redirect_uri, state)
    frappe.cache().set_value(f"oauth_state_{state}", cache_data, expires_in_sec=180)

    # frappe.logger().info(auth_url)
    return {"authorization_url": auth_url, "state": state}


def get_callback_url(platform: str) -> str:
    return f"{get_url()}/api/method/frappe_social.frappe_social.api.oauth.callback_{platform.lower()}"


def _get_auth_url(platform: str, settings, redirect_uri: str, state: str) -> str:
    """Build OAuth authorization URL"""
    if platform == "Twitter":
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
        )
        frappe.cache().set_value(
            f"twitter_verifier_{state}",
            code_verifier,
            expires_in_sec=600,
        )
        params = {
            "response_type": "code",
            "client_id": settings.twitter_client_id,
            "redirect_uri": redirect_uri,
            "scope": "tweet.read tweet.write users.read offline.access",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"https://twitter.com/i/oauth2/authorize?{'&'.join(f'{k}={frappe.utils.quoted(str(v))}' for k,v in params.items())}"

    elif platform == "LinkedIn":
        params = {
            "response_type": "code",
            "client_id": settings.linkedin_client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": "openid profile email w_member_social r_organization_admin w_organization_social",
        }
        return f"https://www.linkedin.com/oauth/v2/authorization?{'&'.join(f'{k}={frappe.utils.quoted(str(v))}' for k,v in params.items())}"

    elif platform in ["Instagram", "Facebook"]:
        scopes = [
            "public_profile",
            "pages_show_list",
            "pages_read_engagement",
            "pages_manage_posts",
            "pages_manage_engagement",
            "read_insights",
            "pages_read_user_content",
            "publish_video"           
        ]
        if platform == "Instagram":
            scopes = ["instagram_basic", "instagram_content_publish", "instagram_manage_insights", "instagram_manage_comments"]
        params = {
            "client_id": settings.meta_app_id,
            "redirect_uri": redirect_uri,
            "scope": ",".join(scopes),
            "state": state,
            "response_type": "code",
        }
        return f"https://www.facebook.com/{api_version}/dialog/oauth?{'&'.join(f'{k}={frappe.utils.quoted(str(v))}' for k,v in params.items())}"


    elif platform == "YouTube":
        params = {
            "client_id": settings.youtube_client_id,
            "redirect_uri": redirect_uri,
            "scope": "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube https://www.googleapis.com/auth/userinfo.profile https://www.googleapis.com/auth/userinfo.email",
            "state": state,
            "response_type": "code",
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"https://accounts.google.com/o/oauth2/v2/auth?{'&'.join(f'{k}={frappe.utils.quoted(str(v))}' for k,v in params.items())}"

    frappe.throw(_(f"Unknown platform: {platform}"))


# =============================================================================
# OAuth Callbacks
# =============================================================================


@frappe.whitelist(allow_guest=True)
def callback_twitter():
    code, state, error = (
        frappe.request.args.get("code"),
        frappe.request.args.get("state"),
        frappe.request.args.get("error"),
    )
    if error:
        return _oauth_error_redirect(f"Twitter: {error}")

    cache_data = frappe.cache().get_value(f"oauth_state_{state}")
    code_verifier = frappe.cache().get_value(f"twitter_verifier_{state}")
    if not cache_data or cache_data.get("platform") != "Twitter" or not code_verifier:
        return _oauth_error_redirect("Invalid OAuth state")

    settings = frappe.get_single("Social Settings")
    response = requests.post(
        "https://api.twitter.com/2/oauth2/token",
        data={
            "code": code,
            "grant_type": "authorization_code",
            "client_id": settings.twitter_client_id,
            "redirect_uri": get_callback_url("Twitter"),
            "code_verifier": code_verifier,
        },
        auth=(settings.twitter_client_id, settings.get_password("twitter_client_secret")),
    )

    if response.status_code != 200:
        return _oauth_error_redirect(f"Token exchange failed: {response.text}")

    token_data = response.json()
    user_response = requests.get(
        "https://api.twitter.com/2/users/me",
        params={"user.fields": "profile_image_url,public_metrics"},
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
    )
    user_data = user_response.json().get("data", {})

    frappe.set_user(cache_data["user"])
    integration = _save_integration(
        platform="Twitter",
        profile_id=user_data.get("id"),
        profile_name=user_data.get("username"),
        profile_image=user_data.get("profile_image"),
        access_token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        expires_in=token_data.get("expires_in", 7200),
        account_type="Personal",
        account_name=cache_data.get("account_name"),
        account_description=cache_data.get("account_description"),
        organization=cache_data.get("organization"),
    )

    frappe.cache().delete_value(f"oauth_state_{state}")
    frappe.cache().delete_value(f"twitter_verifier_{state}")
    return _oauth_success_redirect(integration.name)


@frappe.whitelist(allow_guest=True)
def callback_linkedin():
    code, state, error = (
        frappe.request.args.get("code"),
        frappe.request.args.get("state"),
        frappe.request.args.get("error"),
    )
    if error:
        return _oauth_error_redirect(f"LinkedIn: {error}")

    cache_data = frappe.cache().get_value(f"oauth_state_{state}")
    if not cache_data or cache_data.get("platform") != "LinkedIn":
        return _oauth_error_redirect("Invalid OAuth state")

    settings = frappe.get_single("Social Settings")
    response = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            # "redirect_uri": get_callback_url("LinkedIn"),
            "client_id": settings.linkedin_client_id,
            "client_secret": settings.get_password("linkedin_client_secret"),
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if response.status_code != 200:
        return _oauth_error_redirect(f"Token exchange failed: {response.text}")

    token_data = response.json()
    user_data = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
    ).json()

    frappe.set_user(cache_data["user"])
    integration = _save_integration(
        platform="LinkedIn",
        profile_id=user_data.get("sub"),
        profile_name=user_data.get("name"),
        profile_image=user_data.get("picture"),
        access_token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        expires_in=token_data.get("expires_in", 5184000),
        account_type="Personal",
        account_name=cache_data.get("account_name"),
        account_description=cache_data.get("account_description"),
        organization=cache_data.get("organization"),
    )

    frappe.cache().delete_value(f"oauth_state_{state}")
    return _oauth_success_redirect(integration.name)

@frappe.whitelist(allow_guest=True)
def callback_youtube():
    code, state, error = (
        frappe.request.args.get("code"),
        frappe.request.args.get("state"),
        frappe.request.args.get("error"),
    )
    if error:
        return _oauth_error_redirect(f"YouTube: {error}")

    cache_data = frappe.cache().get_value(f"oauth_state_{state}")
    if not cache_data or cache_data.get("platform") != "YouTube":
        return _oauth_error_redirect("Invalid OAuth state")

    settings = frappe.get_single("Social Settings")
    response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": settings.youtube_client_id,
            "client_secret": settings.get_password("youtube_client_secret"),
            "redirect_uri": get_callback_url("YouTube"),
            "grant_type": "authorization_code",
        },
    )

    if response.status_code != 200:
        return _oauth_error_redirect(f"Token exchange failed: {response.text}")

    token_data = response.json()
    user_info = requests.get(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
    ).json()

    channel_data = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"access_token": token_data["access_token"], "part": "snippet,statistics", "mine": "true"},
    ).json()
    channels = channel_data.get("items", [])

    if not channels:
        return _oauth_error_redirect("No YouTube channel found")

    channel = channels[0]
    snippet, stats = channel.get("snippet", {}), channel.get("statistics", {})

    frappe.set_user(cache_data["user"])
    integration = _save_integration(
        platform="YouTube",
        channel_id=channel["id"],
        channel_name=snippet.get("title"),
        profile_image=snippet.get("thumbnails", {}).get("high", {}).get("url"),
        access_token=token_data.get("access_token"),
        refresh_token=token_data.get("refresh_token"),
        expires_in=token_data.get("expires_in", 3600),
        account_type="Channel",
        followers_count=int(stats.get("subscriberCount", 0)),
        account_name=cache_data.get("account_name"),
        account_description=cache_data.get("account_description"),
        organization=cache_data.get("organization"),
        authorized_user_id=user_info.get("id"),
        authorized_user_name=user_info.get("name"),  
        authorized_user_email=user_info.get("email"),
    )

    frappe.cache().delete_value(f"oauth_state_{state}")
    return _oauth_success_redirect(integration.name)

# =============================================================================
# Meta (Facebook/Instagram) Handler
# =============================================================================


@frappe.whitelist(allow_guest=True)
def callback_facebook():
    return _handle_meta_callback("Facebook")


@frappe.whitelist(allow_guest=True)
def callback_instagram():
    return _handle_meta_callback("Instagram")


def _handle_meta_callback(platform: str):
    """Handle Facebook/Instagram OAuth callback"""
    code, state, error = (
        frappe.request.args.get("code"),
        frappe.request.args.get("state"),
        frappe.request.args.get("error"),
    )
    if error:
        return _oauth_error_redirect(f"{platform}: {error}")

    cache_data = frappe.cache().get_value(f"oauth_state_{state}")
    if not cache_data or cache_data.get("platform") != platform:
        return _oauth_error_redirect("Invalid OAuth state")

    # Get long-lived token
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

    long_token_data = requests.get(
        f"https://graph.facebook.com/{api_version}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": settings.meta_app_id,
            "client_secret": settings.get_password("meta_app_secret"),
            "fb_exchange_token": short_token,
        },
    ).json()

    user_token = long_token_data.get("access_token", short_token)
    expires_in = long_token_data.get("expires_in", 5184000)

    # Get user info
    me_data = requests.get(
        f"https://graph.facebook.com/{api_version}/me",
        params={"access_token": user_token, "fields": "id,name,email"},
    ).json()

    # Get pages
    pages = (
        requests.get(
            f"https://graph.facebook.com/{api_version}/me/accounts",
            params={"access_token": user_token, "fields": "id,name,tasks,access_token,picture{url},fan_count"},
        )
        .json()
        .get("data", [])
    )
    
    approved_pages = [
        page for page in pages
        if page.get("tasks")
    ]


    if not approved_pages:
        return _oauth_error_redirect("No Facebook Pages found. Create a Page first.")

    frappe.set_user(cache_data["user"])
    
    # For Instagram, get linked IG accounts
    if platform == "Instagram":
        ig_pages = []
        for page in pages:
            ig_data = requests.get(
                f"https://graph.facebook.com/{api_version}/{page['id']}",
                params={
                    "access_token": page["access_token"],
                    "fields": "instagram_business_account{id,username,profile_picture_url,followers_count}",
                },
            ).json()
            if ig_data.get("instagram_business_account"):
                ig = ig_data["instagram_business_account"]
                ig_pages.append(
                    {
                        "page_id": page["id"],
                        "page_name": page["name"],
                        "page_access_token": page["access_token"],
                        "instagram_id": ig["id"],
                        "instagram_username": ig.get("username", ""),
                        "followers_count": ig.get("followers_count", 0),
                        "profile_picture_url": ig.get("profile_picture_url", ""),
                    }
                )
        if not ig_pages:
            return _oauth_error_redirect("No Instagram Business accounts found. Make sure your Instagram account is linked to a Facebook Page and converted to a Business account.")
        
        for ig_page in ig_pages:
            try:
                integration = _save_integration(
                    platform=platform,
                    profile_id=ig_page["instagram_id"],
                    profile_name=ig_page["instagram_username"],
                    profile_image=ig_page.get("profile_picture_url"),
                    page_access_token=ig_page["page_access_token"],
                    access_token=user_token,
                    expires_in=expires_in,
                    account_type="Business",
                    authorized_user_id=me_data.get("id"),
                    authorized_user_name=me_data.get("name"),
                    authorized_user_email=me_data.get("email"),
                    followers_count=ig_page.get("followers_count", 0),
                    account_name=cache_data.get("account_name") or ig_page["instagram_username"],  # Fallback added
                    account_description=cache_data.get("account_description"),
                    organization=cache_data.get("organization"),
                )
                frappe.logger().info(f"Instagram integration created: {integration.name}")
            except Exception as e:
                error_msg = f"Failed to save Instagram page {ig_page.get('instagram_username')}: {str(e)}"
                frappe.logger().error(error_msg)
                frappe.log_error(frappe.get_traceback(), "Instagram Integration Creation Failed")
                continue
                
    else:
        for page in approved_pages:
            try:
                integration = _save_integration(
                    platform=platform,
                    page_name=page["name"],
                    page_id=page["id"],
                    profile_image=page.get("picture", {}).get("data", {}).get("url"),
                    page_access_token=page["access_token"],
                    access_token=user_token,
                    expires_in=expires_in,
                    account_type="Page",
                    followers_count=page.get("fan_count", 0),
                    authorized_user_id=me_data.get("id"),
                    authorized_user_name=me_data.get("name"),
                    authorized_user_email=me_data.get("email"),
                    account_name=cache_data.get("account_name") or page["name"],
                    account_description=cache_data.get("account_description"),
                    organization=cache_data.get("organization"),
                )
                frappe.logger().info(f"Facebook integration created: {integration.name}")
                
            except Exception as e:
                error_msg = f"Failed to save {platform} page {page.get('name')}: {str(e)}"
                frappe.logger().error(error_msg)
                frappe.log_error(frappe.get_traceback(), f"{platform} Integration Creation Failed")
                continue
        
    frappe.cache().delete_value(f"oauth_state_{state}")
    return _oauth_success_redirect("new")

def _save_integration(
    platform: str,
    profile_name: str = None,
    profile_id: str = None,
    profile_image: str = None,
    page_name: str = None,
    page_id: str = None,
    channel_id: str = None,
    channel_name: str = None,
    access_token: str = None,
    page_access_token: str = None,
    refresh_token: str = None,
    expires_in: int = None,
    account_type: str = None,
    followers_count: int = 0,
    account_name: str = None,
    organization: str = None,
    account_description: str = None,
    authorized_user_id: str = None,
    authorized_user_name: str = None,
    authorized_user_email: str = None,
):
    """Create or update Social Integration"""
    
    # CRITICAL FIX: account_name is REQUIRED field - use fallback
    if not account_name:
        account_name = profile_name or page_name or channel_name or f"{platform} Account"
    
    try:
        # Only search with profile_id if it exists
        existing = None
        if profile_id :
            existing = frappe.db.get_value(
                "Social Integration", 
                {"platform": platform, "profile_id": profile_id}, 
                "name"
            )
        
        # If no existing found by profile_id, try by profile_name 
        if not existing and page_id:
            existing = frappe.db.get_value(
                "Social Integration", 
                {"platform": platform, "page_id": page_id}, 
                "name"
            )
            
        if not existing and channel_id:
            existing = frappe.db.get_value(
                "Social Integration", 
                {"platform": platform, "channel_id": channel_id}, 
                "name"
            )

        if existing:
            integration = frappe.get_doc("Social Integration", existing)
            frappe.logger().info(f"Updating existing integration: {existing}")
        else:
            integration = frappe.new_doc("Social Integration")
            integration.platform = platform
            frappe.logger().info(f"Creating new {platform} integration for {profile_name or page_name or channel_name}")

        # Set required fields first
        integration.account_name = account_name  # REQUIRED
        integration.connection_status = "Connected"
        integration.enabled = 1
        integration.last_error = None
        
        
        # Set optional fields
        if profile_name:
            integration.profile_name = profile_name
        if page_name:
            integration.page_name = page_name
        if profile_id:
            integration.profile_id = profile_id
        if page_id:
            integration.page_id = page_id
        if profile_image:
            integration.profile_image = profile_image
        if channel_id:
            integration.channel_id = channel_id
        if channel_name:
            integration.channel_name = channel_name
        if access_token:
            integration.access_token = access_token
        if page_access_token:
            integration.page_access_token = page_access_token
        if refresh_token:
            integration.refresh_token = refresh_token
        if expires_in:
            integration.token_expiry = add_to_date(now_datetime(), seconds=expires_in)
        if account_type:
            integration.account_type = account_type
        if followers_count:
            integration.followers_count = followers_count
        if account_description:
            integration.account_description = account_description
        if organization:
            integration.organization = organization        
        if authorized_user_id:
            integration.authorized_user_id = authorized_user_id
        if authorized_user_name:
            integration.authorized_user_name = authorized_user_name
        if authorized_user_email:
            integration.authorized_user_email = authorized_user_email
        
        # Save the document
        integration.save(ignore_permissions=True)
        frappe.logger().info(f"Successfully saved integration: {integration.name}")

        # Handle profile image download (non-critical)
        if profile_image:
            try:
                response = requests.get(profile_image, timeout=10)
                if response.status_code == 200:
                    content_type = response.headers.get("content-type", "image/jpeg")
                    ext = content_type.split("/")[-1]
                    if ext not in ["jpeg", "jpg", "png", "gif", "webp"]:
                        ext = "jpg"

                    file_name = f"{platform}_{profile_name}_profile.{ext}".replace(" ", "_")

                    file_doc = frappe.get_doc({
                        "doctype": "File",
                        "file_name": file_name,
                        "attached_to_doctype": "Social Integration",
                        "attached_to_name": integration.name,
                        "attached_to_field": "profile_image",
                        "content": response.content,
                        "is_private": 0,
                        "decode": False,
                    })
                    file_doc.insert(ignore_permissions=True)

                    integration.profile_image = file_doc.file_url
                    integration.save(ignore_permissions=True)
                    frappe.logger().info(f"Profile image saved for {integration.name}")

            except Exception as e:
                frappe.log_error(
                    f"Failed to fetch profile image for {profile_name}: {str(e)}", 
                    "OAuth Profile Image Download"
                )
                # Don't fail the whole integration if image download fails

        frappe.db.commit()
        return integration

    except Exception as e:
        frappe.db.rollback()
        error_msg = f"Failed to save {platform} integration for {profile_name}: {str(e)}"
        frappe.logger().error(error_msg)
        frappe.log_error(frappe.get_traceback(), f"Social Integration Save Failed - {platform}")
        raise Exception(error_msg)


@frappe.whitelist()
def disconnect(integration: str) -> dict:
    doc = frappe.get_doc("Social Integration", integration)
    doc.connection_status = "Not Connected"
    doc.access_token = doc.refresh_token = doc.page_access_token = None
    doc.save(ignore_permissions=True)
    return {"success": True}


@frappe.whitelist()
def test_connection(integration: str) -> dict:
    """Test if integration's connection is valid"""
    doc = frappe.get_doc("Social Integration", integration)
    settings = frappe.get_single("Social Settings")

    try:
        if doc.platform == "Twitter":
            valid = (
                requests.get(
                    "https://api.twitter.com/2/users/me",
                    headers={"Authorization": f"Bearer {doc.get_password('access_token')}"},
                ).status_code
                == 200
            )
        elif doc.platform == "LinkedIn":
            valid = (
                requests.get(
                    "https://api.linkedin.com/v2/userinfo",
                    headers={"Authorization": f"Bearer {doc.get_password('access_token')}"},
                ).status_code
                == 200
            )
        elif doc.platform in ["Facebook", "Instagram"]:
            token = doc.get_password("page_access_token") or doc.get_password("access_token")
            valid = (
                requests.get(
                    f"https://graph.facebook.com/{settings.meta_api_version or 'v24.0'}/me",
                    params={"access_token": token},
                ).status_code
                == 200
            )
        elif doc.platform == "YouTube":
            valid = (
                requests.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={
                        "access_token": doc.get_password("access_token"),
                        "part": "snippet",
                        "mine": "true",
                    },
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


def _oauth_error_redirect(message: str):
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = f"/app/social-integration?error={frappe.utils.quoted(message)}"


def _oauth_success_redirect(integration_name: str, platform: str = None):
    """Render success page that auto-closes popup"""
    
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = f"/app/social-integration?oauth_success={integration_name}&platform={platform or ''}"
