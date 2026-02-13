app_name = "frappe_social"
app_title = "Frappe Social"
app_publisher = "Abhishek Hiremath"
app_description = "Social media scheduling and analytics module for Frappe/ERPNext"
app_email = "abhishek.dev.4949@gmail.com"
app_license = "MIT"
app_version = "1.0.0"

required_apps = ["frappe"]

# Installation
after_install = "frappe_social.install.after_install"

# Scheduled Tasks
scheduler_events = {
    "cron": {
        # Every minute - check for posts to publish
        "* * * * *": ["frappe_social.frappe_social.tasks.publish_scheduled_posts"],
        # Daily at midnight - reset rate limit counters
        "0 0 * * *": ["frappe_social.frappe_social.tasks.reset_rate_limit_counters"],
        # Every 6 hours - fetch daily analytics
        "0 */6 * * *": ["frappe_social.frappe_social.tasks.fetch_daily_analytics"],
    },
    # Hourly - refresh expiring tokens AND fetch analytics
    "hourly": [
        "frappe_social.frappe_social.tasks.refresh_expiring_tokens",
        "frappe_social.frappe_social.tasks.fetch_post_analytics",
        "frappe_social.frappe_social.tasks.refresh_youtube_tokens",
    ],
}

doc_events = {
    "Marketing Campaign": {
        "before_save": "frappe_social.ads_manager.script.campaign.marketing_campaign_before_save",
    }
}
doctype_js = {
    "Marketing Campaign": "public/js/marketing_campaign.js"
}