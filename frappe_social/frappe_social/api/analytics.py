import frappe
from frappe import _
from frappe.utils import today, add_days, now_datetime
from typing import List, Dict, Any
from frappe_social.frappe_social.services.analytics_service import AnalyticsService
from frappe_social.frappe_social.providers import get_provider


@frappe.whitelist()
def fetch_analytics(integration: str) -> dict:
    """Fetch and store account-level analytics for an integration"""
    return AnalyticsService.fetch_account_analytics(integration)


@frappe.whitelist()
def fetch_post_analytics_now(post_name: str) -> dict:
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
