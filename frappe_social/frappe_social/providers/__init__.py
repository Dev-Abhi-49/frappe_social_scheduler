"""
Social Media Providers
"""

from frappe_social.frappe_social.providers.base import BaseProvider, PublishResult, AnalyticsResult, TokenRefreshResult

_PROVIDERS = {
    "Facebook": "frappe_social.frappe_social.providers.facebook.FacebookProvider",
    "Instagram": "frappe_social.frappe_social.providers.instagram.InstagramProvider",
    "LinkedIn": "frappe_social.frappe_social.providers.linkedin.LinkedInProvider",
    "Twitter": "frappe_social.frappe_social.providers.twitter.TwitterProvider",
    "YouTube": "frappe_social.frappe_social.providers.youtube.YouTubeProvider",
}


def get_provider(platform: str):
    """Get provider class for a platform"""
    import frappe
    
    if platform not in _PROVIDERS:
        frappe.throw(f"Unknown platform: {platform}")
    
    return frappe.get_attr(_PROVIDERS[platform])
