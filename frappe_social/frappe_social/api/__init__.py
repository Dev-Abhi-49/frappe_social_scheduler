"""
API module for Frappe Social Media Scheduler

Exposes whitelisted API methods for:
- OAuth authentication and token management
- Post publishing and scheduling
- Analytics retrieval
"""

# OAuth APIs
from frappe_social.frappe_social.api.oauth import (
    initiate_oauth,
    disconnect,
    test_connection,
    # get_available_pages,
    # connect_page,
)

# Post APIs
from frappe_social.frappe_social.api.posts import (
    publish_now,
    schedule,
    cancel,
    # retry,
    validate_content,
)

# Analytics APIs
from frappe_social.frappe_social.api.analytics import (
    fetch_analytics,
    fetch_post_analytics_now,
    get_summary,
    get_post_analytics,
    get_top_posts,
    compare_platforms,
)

__all__ = [
    # OAuth
    "initiate_oauth",
    "disconnect",
    "test_connection",
    "get_available_pages",
    "connect_page",
    # Posts
    "publish_now",
    "schedule",
    "cancel",
    # 'retry',
    "validate_content",
    # Analytics
    "fetch_analytics",
    "fetch_post_analytics_now",
    "get_summary",
    "get_post_analytics",
    "get_top_posts",
    "compare_platforms",
]
