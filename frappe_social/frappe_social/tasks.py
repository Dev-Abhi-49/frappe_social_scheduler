"""
Scheduled Tasks for Frappe Social

Configured in hooks.py:
scheduler_events = {
    "cron": {
        "* * * * *": ["frappe_social.frappe_social.tasks.publish_scheduled_posts"],
        "0 0 * * *": ["frappe_social.frappe_social.tasks.reset_rate_limit_counters"],
        "0 */6 * * *": ["frappe_social.frappe_social.tasks.fetch_daily_analytics"],
    },
    "hourly": [
        "frappe_social.frappe_social.tasks.refresh_expiring_tokens",
        "frappe_social.frappe_social.tasks.fetch_post_analytics"
    ],
}
"""

import frappe
from frappe.utils import now_datetime, add_days


def publish_scheduled_posts():
    """Publish posts that are scheduled and due (runs every minute)"""
    from frappe_social.frappe_social.services.post_service import PostService

    posts = frappe.get_all(
        "Social Post", filters={"status": "Scheduled", "scheduled_time": ["<=", now_datetime()]}, pluck="name"
    )

    for name in posts:
        try:
            frappe.enqueue(
                PostService.publish_post,
                post_name=name,
                queue="short",
                job_name=f"publish_{name}",
                job_id=f"publish_post:{name}",
                deduplicate=True,
            )
        except Exception as e:
            frappe.log_error(f"Failed to enqueue {name}: {e}", "Social Post Scheduler")


def refresh_expiring_tokens():
    """Refresh tokens expiring within 5 days (runs hourly)"""
    from frappe_social.frappe_social.services.token_service import TokenService

    threshold = add_days(now_datetime(), 5)

    # Fixed: Use list-style filters to avoid duplicate key issue
    integrations = frappe.get_all(
        "Social Integration",
        filters=[["enabled", "=", 1], ["token_expiry", "<=", threshold], ["token_expiry", "is", "set"]],
        pluck="name",
    )

    for name in integrations:
        try:
            frappe.enqueue(
                TokenService.refresh_token,
                integration_name=name,
                queue="short",
                job_name=f"refresh_token_{name}",
                job_id=f"refresh_token:{name}",
                deduplicate=True,
            )
        except Exception as e:
            frappe.log_error(f"Token refresh failed {name}: {e}", "Token Refresh")


def fetch_daily_analytics():
    """Fetch account analytics for all integrations (runs hourly)"""
    from frappe_social.frappe_social.services.analytics_service import AnalyticsService

    integrations = frappe.get_all(
        "Social Integration", filters={"enabled": 1, "connection_status": "Connected"}, pluck="name"
    )

    for name in integrations:
        try:
            frappe.enqueue(
                AnalyticsService.fetch_account_analytics,
                integration_name=name,
                queue="long",
                job_name=f"analytics_{name}",
                job_id=f"analytics_fetch:{name}",
                deduplicate=True,
            )
        except Exception as e:
            frappe.log_error(f"Analytics fetch failed {name}: {e}", "Analytics Fetch")


def fetch_post_analytics():
    """Fetch analytics for recent posts (runs hourly)"""
    from frappe_social.frappe_social.services.analytics_service import AnalyticsService

    posts = AnalyticsService.get_recent_posts_for_analytics()

    for info in posts:
        try:
            frappe.enqueue(
                AnalyticsService.fetch_post_analytics,
                post_name=info["post_name"],
                platform=info["platform"],
                queue="long",
                job_name=f"post_analytics_{info['post_name']}_{info['platform']}",
                job_id=f"post_analytics_fetch:{info['post_name']}:{info['platform']}",
                deduplicate=True,
            )
        except Exception as e:
            frappe.log_error(f"Post analytics failed: {e}", "Post Analytics Fetch")


def reset_rate_limit_counters():
    """Reset daily rate limit counters (runs at midnight)

    Note: Function name must match hooks.py scheduler_events
    Previously named reset_daily_counters which caused import errors
    """
    # Clear cache-based rate limits
    for platform in ["twitter", "linkedin", "instagram", "facebook", "youtube"]:
        frappe.cache.delete_value(f"social_rate_limit_{platform}")

    # Reset database counters in Social Settings
    try:
        settings = frappe.get_single("Social Settings")
        settings.youtube_quota_used = 0
        settings.twitter_posts_today = 0
        settings.instagram_posts_today = 0
        settings.save(ignore_permissions=True)
        frappe.db.commit()

        frappe.logger().info("Social rate limit counters reset successfully")
    except Exception as e:
        frappe.log_error(f"Failed to reset rate limit counters: {e}", "Rate Limit Reset")
