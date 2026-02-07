# meta_mappings.py

OBJECTIVE_TO_PERFORMANCE_GOALS = {
    "Awareness": [
        "Maximise reach of ads",
        "Maximise number of impression",
        "Maximise ad recall lift",
        "Maximise ThruPlay views",
        "Maximise 2-second continuous video plays"
    ],
    "Traffic": [
        "Maximise number of link clicks",
        "Maximise number of landing page views"
    ],
    "Engagement": [
        "Maximise engagement with a post",
        "Maximise number of Page likes",
        "Maximise number of event responses"
    ],
    "Leads": [
        "Maximise number of leads",
        "Maximise number of conversion leads",
        "Maximise number of leads through messaging"
    ],
    "Sales": [
        "Maximise value of conversions"
    ],
    "App promotion": [
        "Maximise number of app installs"
    ],
}

PERFORMANCE_TO_OPTIMIZATION = {
    "Maximise reach of ads": "REACH",
    "Maximise number of impression": "IMPRESSIONS",
    "Maximise ad recall lift": "AD_RECALL_LIFT",
    "Maximise ThruPlay views": "THRUPLAY",
    "Maximise 2-second continuous video plays": "VIDEO_VIEWS",
    "Maximise number of landing page views": "LANDING_PAGE_VIEWS",
    "Maximise number of link clicks": "LINK_CLICKS",
    "Maximise engagement with a post": "POST_ENGAGEMENT",
    "Maximise number of Page likes": "PAGE_LIKES",
    "Maximise number of leads": "LEAD_GENERATION",
    "Maximise number of app installs": "APP_INSTALLS",
    "Maximise value of conversions": "VALUE",
}

OPTIMIZATION_TO_BILLING = {
    "REACH": "IMPRESSIONS",
    "IMPRESSIONS": "IMPRESSIONS",
    "AD_RECALL_LIFT": "IMPRESSIONS",
    "LINK_CLICKS": "LINK_CLICKS",
    "LANDING_PAGE_VIEWS": "IMPRESSIONS",
    "POST_ENGAGEMENT": "IMPRESSIONS",
    "PAGE_LIKES": "PAGE_LIKES",
    "THRUPLAY": "THRUPLAY",
    "VIDEO_VIEWS": "THRUPLAY",
    "LEAD_GENERATION": "IMPRESSIONS",
    "CONVERSIONS": "IMPRESSIONS",
    "VALUE": "IMPRESSIONS",
    "APP_INSTALLS": "IMPRESSIONS",
}
