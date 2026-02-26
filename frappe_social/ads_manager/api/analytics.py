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
