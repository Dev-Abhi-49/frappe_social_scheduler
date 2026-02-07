"""
Ad Providers
"""

_PROVIDERS = {
    "Facebook": "ads_manager.ads_manager.providers.meta_ads.MetaAdsProvider",
    "Instagram": "ads_manager.ads_manager.providers.meta_ads.MetaAdsProvider",
    "Meta": "ads_manager.ads_manager.providers.meta_ads.MetaAdsProvider",
}


def get_provider(platform: str):
    """Get provider class for a platform"""
    import frappe

    if platform not in _PROVIDERS:
        frappe.throw(f"Unknown platform: {platform}")

    return frappe.get_attr(_PROVIDERS[platform])
