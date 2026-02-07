import frappe
from datetime import datetime
from frappe.utils import now_datetime, today, add_days, getdate
from typing import Dict, Any, List
from frappe_social.frappe_social.providers import get_provider


class AnalyticsService:
    POST_ANALYTICS_LOOKBACK_DAYS = 7

    @staticmethod
    def fetch_account_analytics(integration_name: str) -> Dict[str, Any]:
        """Fetch and store account-level analytics"""
        try:
            integration = frappe.get_doc("Social Integration", integration_name)
        except frappe.DoesNotExistError:
            return {"success": False, "error_message": "Integration not found"}

        if not integration.enabled or integration.connection_status != "Connected":
            return {"success": False, "error_message": "Not enabled or connected"}

        try:
            provider = get_provider(integration.platform)(integration_name)
            result = provider.fetch_account_analytics()
            if not result.success:
                return {"success": False, "error_message": result.error_message}

            # Get or create analytics doc for today
            existing = frappe.db.exists(
                "Social Analytics", {"integration": integration_name, "date": today()}
            )
            if existing:
                analytics = frappe.get_doc("Social Analytics", existing)
                # Clear existing metrics to prevent duplicates
                analytics.metrics = []
            else:
                analytics = frappe.new_doc("Social Analytics")
            analytics.integration = integration_name
            analytics.platform = integration.platform
            analytics.date = today()

            # Get previous day's data for change calculation
            previous = AnalyticsService._get_previous_analytics(integration_name)

            # Update standard metric fields
            for field in [
                "followers_count",
                "following_count",
                "posts_count",
                "impressions",
                "reach",
                "likes",
                "comments",
                "shares",
                "saves",
                "video_views",
            ]:
                if field in result.metrics:
                    setattr(analytics, field, result.metrics[field])

            # Store all metrics in detailed metrics table with change tracking
            for metric_name, value in result.metrics.items():
                prev_value = previous.get(metric_name, 0) if previous else 0
                change = value - prev_value
                change_percent = (change / prev_value * 100) if prev_value != 0 else 0
                analytics.append(
                    "metrics",
                    {
                        "metric_name": metric_name,
                        "metric_value": value,
                        "previous_value": prev_value,
                        "change": change,
                        "change_percent": round(change_percent, 2),
                    },
                )

            analytics.save(ignore_permissions=True)

            # Update integration followers
            if result.metrics.get("followers_count"):
                integration.followers_count = result.metrics["followers_count"]
                integration.save(ignore_permissions=True)

            frappe.db.commit()
            return {"success": True, "analytics_doc": analytics.name, "metrics": result.metrics}
        except Exception as e:
            frappe.log_error(
                message=f"Integration: {integration_name}\nError: {str(e)}", title="Analytics Fetch Error"
            )
            return {"success": False, "error_message": str(e)}

    @staticmethod
    def _get_previous_analytics(integration_name: str) -> Dict[str, Any]:
        """Get previous day's analytics for change calculation"""
        yesterday = add_days(today(), -1)
        existing = frappe.db.exists("Social Analytics", {"integration": integration_name, "date": yesterday})
        if not existing:
            return {}
        prev_doc = frappe.get_doc("Social Analytics", existing)
        result = {}
        # Get values from child table
        for row in prev_doc.metrics:
            result[row.metric_name] = row.metric_value
        # Also get from main fields
        for field in [
            "followers_count",
            "following_count",
            "posts_count",
            "impressions",
            "reach",
            "likes",
            "comments",
            "shares",
            "saves",
            "video_views",
        ]:
            val = getattr(prev_doc, field, None)
            if val:
                result[field] = val
        return result

    @staticmethod
    def fetch_post_analytics(post_name: str, platform: str = None) -> Dict[str, Any]:
        """Fetch and store analytics for a single post (no child table needed)"""
        try:
            post = frappe.get_doc("Social Post", post_name)
        except frappe.DoesNotExistError:
            return {"success": False, "error_message": "Post not found"}

        if post.status != "Published":
            return {"success": False, "error_message": "Post not published"}

        platform = platform or post.platform
        if not platform:
            return {"success": False, "error_message": "No platform set"}

        if not post.post_id:
            return {"success": False, "error_message": "No post ID stored"}

        # Find the connected integration
        integrations = frappe.get_all(
            "Social Integration",
            filters={"platform": platform, "enabled": 1, "connection_status": "Connected"},
            limit=1,
            pluck="name",
        )
        if not integrations:
            return {"success": False, "error_message": "No connected integration for this platform"}

        integration_name = integrations[0]

        try:
            provider = get_provider(platform)(integration_name)
            result = provider.fetch_post_analytics(post.post_id)

            if not result.success:
                return {"success": False, "error_message": result.error_message or "API failed"}

            # Prevent duplicate fetch today
            today_start = datetime.combine(getdate(today()), datetime.min.time())

            existing = frappe.db.exists(
                "Social Post Analytics", {"social_post": post_name, "fetched_at": [">=", today_start]}
            )

            if existing:
                analytics = frappe.get_doc("Social Post Analytics", existing)
            else:
                analytics = frappe.new_doc("Social Post Analytics")

            analytics.social_post = post_name
            analytics.platform = platform
            analytics.integration = integration_name
            analytics.post_id = post.post_id
            analytics.fetched_at = now_datetime()

            # Update metrics
            metrics_map = {
                "impressions": "impressions",
                "reach": "reach",
                "likes": "likes",
                "comments": "comments",
                "shares": "shares",
                "saves": "saves",
                "clicks": "clicks",
                "video_views": "video_views",
                "engagement_rate": "engagement_rate",
            }

            for src, dest in metrics_map.items():
                if src in result.metrics:
                    setattr(analytics, dest, result.metrics[src])

            analytics.save(ignore_permissions=True)
            frappe.db.commit()

            return {"success": True, "metrics": result.metrics}

        except Exception as e:
            frappe.log_error(f"Post Analytics Fetch Failed: {str(e)}", "Analytics Service")
            return {"success": False, "error_message": str(e)}

    @staticmethod
    def get_recent_posts_for_analytics() -> List[Dict[str, Any]]:
        """Get recently published posts for scheduled analytics fetch (no child table)"""
        cutoff = add_days(today(), -AnalyticsService.POST_ANALYTICS_LOOKBACK_DAYS)

        posts = frappe.get_all(
            "Social Post",
            filters={
                "status": "Published",
                "published_time": [">=", cutoff],
                "post_id": ["!=", ""],  # Has post_id
            },
            fields=["name", "platform"],
        )

        result = []
        for post in posts:
            result.append({"post_name": post.name, "platform": post.platform})
        return result

    @staticmethod
    def get_analytics_summary(integration_name: str, days: int = 30) -> Dict[str, Any]:
        """Get analytics summary"""
        start_date = add_days(today(), -days)
        data = frappe.get_all(
            "Social Analytics",
            filters={"integration": integration_name, "date": [">=", start_date]},
            fields=["*"],
            order_by="date asc",
        )
        if not data:
            return {"has_data": False}
        return {
            "has_data": True,
            "period_days": days,
            "data_points": len(data),
            "totals": {
                "impressions": sum(d.get("impressions") or 0 for d in data),
                "likes": sum(d.get("likes") or 0 for d in data),
                "comments": sum(d.get("comments") or 0 for d in data),
                "shares": sum(d.get("shares") or 0 for d in data),
            },
            "followers": {
                "start": data[0].get("followers_count") or 0,
                "end": data[-1].get("followers_count") or 0,
                "change": (data[-1].get("followers_count") or 0) - (data[0].get("followers_count") or 0),
            },
        }
