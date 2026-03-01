import frappe
from frappe import _
from frappe.utils import today, add_days, now_datetime
from typing import List, Dict, Any
from frappe_social.frappe_social.services.analytics_service import AnalyticsService
from frappe_social.frappe_social.providers import get_provider
from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider


@frappe.whitelist()
def fetch_analytics(integration: str) -> dict:
    """Fetch and store account-level analytics for an integration"""
    return fetch_ads_account_analytics(integration)


@frappe.whitelist()
def fetch_ads_account_analytics(integration_name: str) -> dict:
    """Fetch and store account-level analytics for an Ads Account Integration"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        # Get the Ads Account Integration document
        integration = frappe.get_doc("Ads Account Integration", integration_name)
        
        if not integration.enabled or integration.connection_status != "Connected":
            return {
                "success": False,
                "error_message": "Account is not connected or enabled"
            }
        
        # Log integration details for debugging
        logger.info(f"=== Starting Analytics Fetch ===")
        logger.info(f"Integration: {integration_name}")
        logger.info(f"Ad Account ID: {integration.ad_account_id}")
        logger.info(f"Platform: {integration.platform}")
        logger.info(f"Access Token exists: {bool(integration.access_token)}")
        logger.info(f"Connection Status: {integration.connection_status}")
        
        # Initialize Meta Ads Provider
        logger.info(f"Initializing MetaAdsProvider...")
        provider = MetaAdsProvider(integration_name)
        logger.info(f"Provider initialized. Account ID: {provider.account_id}")
        
        # Fetch account analytics from Meta API
        logger.info(f"Calling fetch_account_analytics()...")
        result = provider.fetch_account_analytics()
        logger.info(f"API call completed. Success: {result.success}")
        
        if not result.success:
            logger.error(f"Analytics fetch failed: {result.error_message}")
            return {
                "success": False,
                "error_message": result.error_message
            }
        
        logger.info(f"Successfully fetched metrics. Keys: {list(result.metrics.keys())}")
        
        # Check if analytics document already exists for this integration
        existing_analytics = frappe.get_list(
            "Ads Analytics",
            filters={"ads_account_integration": integration_name},
            limit_page_length=1
        )
        
        metrics = result.metrics
        
        # Update existing or create new
        if existing_analytics:
            # Update existing document
            analytics = frappe.get_doc("Ads Analytics", existing_analytics[0].name)
            logger.info(f"Updating existing analytics document: {analytics.name}")
        else:
            # Create new document
            analytics = frappe.new_doc("Ads Analytics")
            analytics.ads_account_integration = integration_name
            logger.info(f"Creating new analytics document for integration: {integration_name}")
        
        # Update fields (works for both new and existing)
        analytics.analytics_date = today()
        analytics.last_synced = now_datetime()
        analytics.sync_status = "Success"
        
        analytics.spend = float(metrics.get("spend", 0) or 0)
        analytics.impressions = int(metrics.get("impressions", 0) or 0)
        analytics.clicks = int(metrics.get("clicks", 0) or 0)
        analytics.ctr = float(metrics.get("ctr", 0) or 0)
        analytics.cpc = float(metrics.get("cpc", 0) or 0)
        analytics.reach = int(metrics.get("reach", 0) or 0)
        analytics.frequency = float(metrics.get("frequency", 0) or 0)
        analytics.actions_count = int(metrics.get("actions", 0) or 0)
        analytics.action_rate = float(metrics.get("action_rate", 0) or 0)
        analytics.cost_per_action = float(metrics.get("cost_per_action", 0) or 0)
        analytics.conversions = int(metrics.get("conversions", 0) or 0)
        analytics.conversion_rate = float(metrics.get("conversion_rate", 0) or 0)
        analytics.purchase_roas = float(metrics.get("purchase_roas", 0) or 0)
        analytics.cost_per_purchase = float(metrics.get("cost_per_purchase", 0) or 0)
        analytics.active_campaigns = int(metrics.get("active_campaigns", 0) or 0)
        analytics.total_campaigns = int(metrics.get("total_campaigns", 0) or 0)
        analytics.adsets_count = int(metrics.get("adsets_count", 0) or 0)
        analytics.ads_count = int(metrics.get("ads_count", 0) or 0)
        
        # Store raw metrics as JSON for reference
        import json
        analytics.raw_metrics = json.dumps(metrics, indent=2)
        analytics.notes = f"Analytics fetched from Meta API. Last 7 days data aggregated."
        
        # Save the analytics document
        analytics.save(ignore_permissions=True)
        frappe.db.commit()
        
        logger.info(f"Analytics saved successfully: {analytics.name}")
        
        return {
            "success": True,
            "analytics_doc": analytics.name,
            "metrics": metrics,
            "message": f"Analytics fetched successfully for {integration.account_name}"
        }
        
    except frappe.DoesNotExistError:
        logger.error(f"Integration not found: {integration_name}")
        return {
            "success": False,
            "error_message": f"Ads Account Integration '{integration_name}' not found"
        }
    except Exception as e:
        logger.exception(f"Error fetching analytics for {integration_name}")
        frappe.log_error(
            message=f"Integration: {integration_name}\nError: {str(e)}",
            title="Ads Analytics Fetch Error"
        )
        return {
            "success": False,
            "error_message": f"Error fetching analytics: {str(e)}"
        }

@frappe.whitelist()
def get_campaign_analytics(integration: str) -> dict:
    """
    Fetch and store campaign-level analytics from Meta Ads API.
    
    Endpoint: GET /{campaign_id}/insights
    Reference: https://developers.facebook.com/docs/marketing-api/reference/ad-campaign-group/insights
    
    Args:
        integration: The name/ID of the Marketing Campaign document
        
    Returns:
        dict with success status, metrics, and campaign analytics document name
    """
    import logging
    import json
    logger = logging.getLogger(__name__)
    
    try:
        campaign_name = integration  # For clarity
        logger.info(f"=== Fetching Campaign Analytics ===")
        logger.info(f"Campaign: {campaign_name}")
        
        # Get the Marketing Campaign document
        marketing_campaign = frappe.get_doc("Marketing Campaign", campaign_name)
        
        # Validate that Meta Ads is enabled for this campaign
        if not getattr(marketing_campaign, "custom_is_meta_ads", False):
            return {
                "success": False,
                "error_message": "This campaign does not have Meta Ads enabled"
            }
        
        # Get the Facebook Campaign ID
        campaign_id = getattr(marketing_campaign, "custom_facebook_campaign_id", None)
        if not campaign_id:
            return {
                "success": False,
                "error_message": "No Facebook Campaign ID found. Please create the campaign first."
            }
        
        # Get the Ad Account Integration to initialize provider
        ad_account_name = getattr(marketing_campaign, "custom_select_facebook_ad_account", None)
        if not ad_account_name:
            return {
                "success": False,
                "error_message": "Ad Account is not selected"
            }
        
        # Verify the integration exists and is connected
        integration_doc = frappe.get_doc("Ads Account Integration", ad_account_name)
        if not integration_doc.enabled or integration_doc.connection_status != "Connected":
            return {
                "success": False,
                "error_message": "Ad Account Integration is not connected or enabled"
            }
        
        logger.info(f"Campaign ID: {campaign_id}")
        logger.info(f"Ad Account: {ad_account_name}")
        
        # Initialize MetaAdsProvider with the integration
        provider = MetaAdsProvider(ad_account_name)
        logger.info(f"Provider initialized with account ID: {provider.account_id}")
        
        # Fetch campaign-level analytics from Meta API
        logger.info(f"Calling fetch_campaign_analytics for campaign {campaign_id}...")
        result = provider.fetch_campaign_analytics(campaign_id)
        
        logger.info(f"API call completed. Success: {result.success}")
        
        if not result.success:
            logger.warning(f"Campaign analytics fetch failed: {result.error_message}")
            return {
                "success": False,
                "error_message": result.error_message or "No analytics data available",
                "message": "📊 No Analytics Available",
                "details": f"Campaign '{campaign_name}' does not have analytics data yet.\n\n"
                          f"This could happen because:\n"
                          f"• Campaign was just created\n"
                          f"• No impressions or activity yet\n"
                          f"• Data is still being processed by Meta\n\n"
                          f"Please try again later."
            }
        
        logger.info(f"Successfully fetched metrics. Keys: {list(result.metrics.keys())}")
        
        # Check if campaign analytics document already exists
        existing_analytics = frappe.get_list(
            "Campaign Analytics",
            filters={
                "marketing_campaign": campaign_name,
                "ads_account_integration": ad_account_name
            },
            limit_page_length=1
        )
        
        metrics = result.metrics
        
        # Update existing or create new
        if existing_analytics:
            # Update existing document
            campaign_analytics = frappe.get_doc("Campaign Analytics", existing_analytics[0].name)
            logger.info(f"Updating existing campaign analytics document: {campaign_analytics.name}")
        else:
            # Create new document
            campaign_analytics = frappe.new_doc("Campaign Analytics")
            campaign_analytics.marketing_campaign = campaign_name
            campaign_analytics.ads_account_integration = ad_account_name
            campaign_analytics.facebook_campaign_id = campaign_id
            logger.info(f"Creating new campaign analytics document")
        
        # Update fields (works for both new and existing)
        campaign_analytics.analytics_date = today()
        campaign_analytics.last_synced = now_datetime()
        campaign_analytics.sync_status = "Success"
        
        # Campaign-level metrics from Meta API
        campaign_analytics.spend = float(metrics.get("spend", 0) or 0)
        campaign_analytics.impressions = int(metrics.get("impressions", 0) or 0)
        campaign_analytics.clicks = int(metrics.get("clicks", 0) or 0)
        campaign_analytics.ctr = float(metrics.get("ctr", 0) or 0)
        campaign_analytics.cpc = float(metrics.get("cpc", 0) or 0)
        campaign_analytics.reach = int(metrics.get("reach", 0) or 0)
        campaign_analytics.frequency = float(metrics.get("frequency", 0) or 0)
        
        # Action metrics
        campaign_analytics.actions_count = int(metrics.get("actions", 0) or 0)
        campaign_analytics.action_rate = float(metrics.get("action_rate", 0) or 0)
        campaign_analytics.cost_per_action = float(metrics.get("cost_per_action", 0) or 0)
        
        # Conversion metrics
        campaign_analytics.conversions = int(metrics.get("conversions", 0) or 0)
        campaign_analytics.conversion_rate = float(metrics.get("conversion_rate", 0) or 0)
        campaign_analytics.cost_per_conversion = float(metrics.get("cost_per_conversion", 0) or 0)
        
        # ROAS metrics
        campaign_analytics.purchase_roas = float(metrics.get("purchase_roas", 0) or 0)
        
        # Video metrics (if applicable)
        campaign_analytics.video_views = int(metrics.get("video_views", 0) or 0)
        campaign_analytics.inline_link_clicks = int(metrics.get("inline_link_clicks", 0) or 0)
        campaign_analytics.outbound_clicks = int(metrics.get("outbound_clicks", 0) or 0)
        
        # Store raw metrics as JSON for reference
        campaign_analytics.raw_metrics = json.dumps(metrics, indent=2)
        campaign_analytics.notes = f"Campaign-level analytics fetched from Meta API. Last 7 days aggregated data."
        
        # Save the analytics document
        campaign_analytics.save(ignore_permissions=True)
        frappe.db.commit()
        
        logger.info(f"Campaign analytics saved successfully: {campaign_analytics.name}")
        
        return {
            "success": True,
            "analytics_doc": campaign_analytics.name,
            "metrics": metrics,
            "message": f"Campaign analytics fetched successfully for {marketing_campaign.custom_campaign_name}"
        }
        
    except frappe.DoesNotExistError as e:
        logger.error(f"Document not found: {str(e)}")
        return {
            "success": False,
            "error_message": f"Document not found: {str(e)}"
        }
    except Exception as e:
        logger.exception(f"Error fetching campaign analytics")
        frappe.log_error(
            message=f"Campaign: {integration}\nError: {str(e)}",
            title="Campaign Analytics Fetch Error"
        )
        return {
            "success": False,
            "error_message": f"Error fetching campaign analytics: {str(e)}"
        }

@frappe.whitelist()
def get_adset_analytics(adset_id: str) -> dict:
    """
    Fetch and store ad set-level analytics from Meta Ads API.
    
    Endpoint: GET /{adset_id}/insights
    Reference: https://developers.facebook.com/docs/marketing-api/reference/ad-set/insights
    
    Args:
        adset_id: The name/ID of the Ad Set document
        
    Returns:
        dict with success status, metrics, and ad set analytics document name
    """
    import logging
    import json
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"=== Fetching Ad Set Analytics ===")
        logger.info(f"Ad Set: {adset_id}")
        
        # Get the Ad Set document
        ad_set = frappe.get_doc("Ad Set", adset_id)
        
        # Get the parent campaign
        campaign_name = ad_set.campaign
        if not campaign_name:
            return {
                "success": False,
                "error_message": "Parent campaign is not set for this ad set"
            }
        
        # Get the Marketing Campaign document to find account integration
        marketing_campaign = frappe.get_doc("Marketing Campaign", campaign_name)
        
        # Validate that Meta Ads is enabled for the parent campaign
        if not getattr(marketing_campaign, "custom_is_meta_ads", False):
            return {
                "success": False,
                "error_message": "Parent campaign does not have Meta Ads enabled"
            }
        
        # Get the Meta Ad Set ID
        meta_adset_id = getattr(ad_set, "adset_id", None)
        if not meta_adset_id:
            return {
                "success": False,
                "error_message": "No Ad Set ID found. Please create the ad set first."
            }
        
        # Get the Ad Account Integration to initialize provider
        ad_account_name = getattr(marketing_campaign, "custom_select_facebook_ad_account", None)
        if not ad_account_name:
            return {
                "success": False,
                "error_message": "Ad Account is not selected"
            }
        
        # Verify the integration exists and is connected
        integration_doc = frappe.get_doc("Ads Account Integration", ad_account_name)
        if not integration_doc.enabled or integration_doc.connection_status != "Connected":
            return {
                "success": False,
                "error_message": "Ad Account Integration is not connected or enabled"
            }
        
        logger.info(f"Ad Set Meta ID: {meta_adset_id}")
        logger.info(f"Parent Campaign: {campaign_name}")
        logger.info(f"Ad Account: {ad_account_name}")
        
        # Initialize MetaAdsProvider with the integration
        provider = MetaAdsProvider(ad_account_name)
        logger.info(f"Provider initialized with account ID: {provider.account_id}")
        
        # Fetch ad set-level analytics from Meta API
        logger.info(f"Calling fetch_adset_analytics for ad set {meta_adset_id}...")
        result = provider.fetch_adset_analytics(meta_adset_id)
        
        logger.info(f"API call completed. Success: {result.success}")
        
        if not result.success:
            logger.warning(f"Ad set analytics fetch failed: {result.error_message}")
            return {
                "success": False,
                "error_message": result.error_message or "No analytics data available",
                "message": "📊 No Analytics Available",
                "details": f"Ad Set '{ad_set.name}' does not have analytics data yet.\n\n"
                          f"This could happen because:\n"
                          f"• Ad set was just created\n"
                          f"• No impressions or activity yet\n"
                          f"• Data is still being processed by Meta\n\n"
                          f"Please try again later."
            }
        
        logger.info(f"Successfully fetched metrics. Keys: {list(result.metrics.keys())}")
        
        # Check if ad set analytics document already exists
        existing_analytics = frappe.get_list(
            "Ad Set Analytics",
            filters={
                "ad_set": adset_id,
                "ads_account_integration": ad_account_name
            },
            limit_page_length=1
        )
        
        metrics = result.metrics
        
        # Update existing or create new
        if existing_analytics:
            # Update existing document
            ad_set_analytics = frappe.get_doc("Ad Set Analytics", existing_analytics[0].name)
            logger.info(f"Updating existing ad set analytics document: {ad_set_analytics.name}")
        else:
            # Create new document
            ad_set_analytics = frappe.new_doc("Ad Set Analytics")
            ad_set_analytics.ad_set = adset_id
            ad_set_analytics.campaign = campaign_name
            ad_set_analytics.ads_account_integration = ad_account_name
            ad_set_analytics.meta_adset_id = meta_adset_id
            logger.info(f"Creating new ad set analytics document")
        
        # Update fields (works for both new and existing)
        ad_set_analytics.analytics_date = today()
        ad_set_analytics.last_synced = now_datetime()
        ad_set_analytics.sync_status = "Success"
        
        # Ad Set-level metrics from Meta API
        ad_set_analytics.spend = float(metrics.get("spend", 0) or 0)
        ad_set_analytics.impressions = int(metrics.get("impressions", 0) or 0)
        ad_set_analytics.clicks = int(metrics.get("clicks", 0) or 0)
        ad_set_analytics.ctr = float(metrics.get("ctr", 0) or 0)
        ad_set_analytics.cpc = float(metrics.get("cpc", 0) or 0)
        ad_set_analytics.reach = int(metrics.get("reach", 0) or 0)
        ad_set_analytics.frequency = float(metrics.get("frequency", 0) or 0)
        
        # Action metrics
        ad_set_analytics.actions_count = int(metrics.get("actions", 0) or 0)
        ad_set_analytics.action_rate = float(metrics.get("action_rate", 0) or 0)
        ad_set_analytics.cost_per_action = float(metrics.get("cost_per_action", 0) or 0)
        
        # Conversion metrics
        ad_set_analytics.conversions = int(metrics.get("conversions", 0) or 0)
        ad_set_analytics.conversion_rate = float(metrics.get("conversion_rate", 0) or 0)
        ad_set_analytics.cost_per_conversion = float(metrics.get("cost_per_conversion", 0) or 0)
        
        # ROAS metrics
        ad_set_analytics.purchase_roas = float(metrics.get("purchase_roas", 0) or 0)
        
        # Video metrics (if applicable)
        ad_set_analytics.video_views = int(metrics.get("video_views", 0) or 0)
        ad_set_analytics.inline_link_clicks = int(metrics.get("inline_link_clicks", 0) or 0)
        ad_set_analytics.outbound_clicks = int(metrics.get("outbound_clicks", 0) or 0)
        
        # Store raw metrics as JSON for reference
        ad_set_analytics.raw_metrics = json.dumps(metrics, indent=2)
        ad_set_analytics.notes = f"Ad Set-level analytics fetched from Meta API. Last 7 days aggregated data."
        
        # Save the analytics document
        ad_set_analytics.save(ignore_permissions=True)
        frappe.db.commit()
        
        logger.info(f"Ad set analytics saved successfully: {ad_set_analytics.name}")
        
        return {
            "success": True,
            "analytics_doc": ad_set_analytics.name,
            "metrics": metrics,
            "message": f"Ad Set analytics fetched successfully for {ad_set.name}"
        }
        
    except frappe.DoesNotExistError as e:
        logger.error(f"Document not found: {str(e)}")
        return {
            "success": False,
            "error_message": f"Document not found: {str(e)}"
        }
    except Exception as e:
        logger.exception(f"Error fetching ad set analytics")
        frappe.log_error(
            message=f"Ad Set: {adset_id}\nError: {str(e)}",
            title="Ad Set Analytics Fetch Error"
        )
        return {
            "success": False,
            "error_message": f"Error fetching ad set analytics: {str(e)}"
        }

@frappe.whitelist()
def get_ads_analytics_summary(integration_name: str, days: int = 7) -> dict:
    """Get analytics summary for an Ads Account Integration"""
    try:
        # Get the latest analytics document for this integration
        analytics = frappe.get_all(
            "Ads Analytics",
            filters={"ads_account_integration": integration_name},
            fields=[
                "name",
                "analytics_date",
                "spend",
                "impressions",
                "clicks",
                "ctr",
                "reach",
                "conversions",
                "conversion_rate",
                "active_campaigns",
                "total_campaigns"
            ],
            order_by="analytics_date desc",
            limit=1
        )
        
        if not analytics:
            return {
                "success": False,
                "message": "No analytics data available"
            }
        
        latest = analytics[0]
        return {
            "success": True,
            "analytics": latest
        }
    except Exception as e:
        frappe.log_error(f"Error getting analytics summary: {str(e)}", "Ads Analytics")
        return {
            "success": False,
            "message": str(e)
        }



    """ Fetch and store analytics for a specific post immediately (can be used for manual refresh) """
    post = frappe.get_doc("Social Post", post_name)
    result = AnalyticsService.fetch_post_analytics(post_name, post.platform)

    if result.get("success"):
        frappe.msgprint("Analytics fetched successfully!")
    else:
        frappe.msgprint(f"Failed: {result.get('error_message')}", indicator="red")

    return result


@frappe.whitelist()
def get_post_analytics(post_name: str) -> dict:
    post = frappe.get_doc("Social Post", post_name)
    if post.status != "Published" or not post.post_id:
        return {"error": "Not published"}

    latest = frappe.get_all(
        "Social Post Analytics",
        filters={"social_post": post_name},
        fields=["*"],
        order_by="fetched_at desc",
        limit=1,
    )
    return {post.platform: latest[0] if latest else {"error": "No data yet"}}


@frappe.whitelist()
def get_summary(integration: str, days: int = 30) -> dict:
    """Get analytics summary for an integration"""
    return AnalyticsService.get_analytics_summary(integration, int(days))


@frappe.whitelist()
def get_top_posts(days: int = 30, limit: int = 10) -> List[dict]:
    """Get top performing posts (adapted for no child table)"""
    try:
        start_date = add_days(today(), -int(days))
        limit_val = int(limit)
        if limit_val <= 0 or limit_val > 100:
            limit_val = 10

        # Since there's no platforms child table, we join on post.platform and analytics.platform
        posts = frappe.db.sql(
            """
            SELECT
                sp.name,
                sp.content,
                sp.published_time,
                sp.platform,
                spa.impressions,
                spa.reach,
                spa.likes,
                spa.comments,
                spa.shares,
                spa.engagement_rate
            FROM `tabSocial Post` sp
            LEFT JOIN `tabSocial Post Analytics` spa
                ON spa.social_post = sp.name
                AND spa.platform = sp.platform
            WHERE sp.status = 'Published'
              AND sp.published_time >= %s
            ORDER BY COALESCE(spa.engagement_rate, 0) DESC
            LIMIT %s
        """,
            (start_date, limit_val),
            as_dict=True,
        )

        return posts or []
    except Exception as e:
        frappe.log_error(f"Error fetching top posts: {str(e)}", "Analytics API")
        return []


@frappe.whitelist()
def compare_platforms(days: int = 30) -> dict:
    """Compare analytics across connected platforms (works with one or many)"""
    try:
        start_date = add_days(today(), -int(days))
        integrations = frappe.get_all(
            "Social Integration", filters={"enabled": 1, "connection_status": "Connected"}, pluck="name"
        )

        if not integrations:
            return {}

        comparison = {}
        for name in integrations:
            try:
                integration = frappe.get_doc("Social Integration", name)
                analytics = frappe.get_all(
                    "Social Analytics",
                    filters={"integration": name, "date": [">=", start_date]},
                    fields=["*"],
                    order_by="date desc",
                )

                if analytics:
                    latest = analytics[0]
                    comparison[name] = {
                        "platform": integration.platform,
                        "profile_name": integration.profile_name,
                        "followers": latest.get("followers_count") or 0,
                        "total_impressions": sum(a.get("impressions") or 0 for a in analytics),
                        "total_engagement": sum(
                            (a.get("likes") or 0) + (a.get("comments") or 0) + (a.get("shares") or 0)
                            for a in analytics
                        ),
                    }
            except Exception as e:
                frappe.log_error(f"Error comparing platform {name}: {str(e)}", "Analytics API")

        return comparison
    except Exception as e:
        frappe.log_error(f"Error in compare_platforms: {str(e)}", "Analytics API")
        return {}
