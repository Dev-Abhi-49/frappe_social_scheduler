# meta_mappings.py
import frappe

OBJECTIVE_TO_PERFORMANCE_GOALS = {
    "Awareness": [
        "Maximise reach of ads",
        "Maximise number of impression",
        "Maximise ad recall lift",
        "Maximise ThruPlay views",
        "Maximise 2-second continuous video plays",
    ],
    "Traffic": [
        "Maximise number of link clicks",
        "Maximise number of landing page views",
        "Maximise daily unique reach",
        "Maximise number of conversations",
    ],
    "Engagement": [
        "Maximise engagement with a post",
        "Maximise number of Page likes",
        "Maximise number of event responses",
        "Maximise daily unique reach",
        "Maximise number of Instagram profile visits",
        "Maximise number of calls",
        "Maximise reminders set",
        "Maximise number of conversations",
        "Maximise ThruPlay views",
        "Maximise 2-second continuous video plays",
    ],
    "Leads": [
        "Maximise number of leads",
        "Maximise number of conversion leads",
        "Maximise number of leads through messaging",
    ],
    "Sales": [
        "Maximise value of conversions",
        "Maximise number of app events",
    ],
    "App promotion": [
        "Maximise number of app installs",
        "Maximise number of app events",
    ],
}

PERFORMANCE_TO_OPTIMIZATION = {
    "Maximise reach of ads":                       "REACH",
    "Maximise number of impression":               "IMPRESSIONS",
    "Maximise ad recall lift":                     "AD_RECALL_LIFT",
    "Maximise ThruPlay views":                     "THRUPLAY",
    "Maximise 2-second continuous video plays":    "TWO_SECOND_CONTINUOUS_VIDEO_VIEWS",
    "Maximise number of link clicks":              "LINK_CLICKS",
    "Maximise number of landing page views":       "LANDING_PAGE_VIEWS",
    "Maximise daily unique reach":                 "REACH",
    "Maximise number of conversations":            "CONVERSATIONS",
    "Maximise number of Instagram profile visits": "VISIT_INSTAGRAM_PROFILE",
    "Maximise number of calls":                    "QUALITY_CALL",
    "Maximise engagement with a post":             "POST_ENGAGEMENT",
    "Maximise number of event responses":          "EVENT_RESPONSES",
    "Maximise number of app events":               "OFFSITE_CONVERSIONS",
    "Maximise reminders set":                      "REMINDERS_SET",
    "Maximise number of Page likes":               "PAGE_LIKES",
    "Maximise number of leads":                    "LEAD_GENERATION",
    "Maximise number of conversion leads":         "QUALITY_LEAD",
    "Maximise number of leads through messaging":  "LEAD_GENERATION",
    "Maximise number of app installs":             "APP_INSTALLS",
    "Maximise value of conversions":               "VALUE",
}

OPTIMIZATION_TO_BILLING = {
    "REACH":                             "IMPRESSIONS",
    "IMPRESSIONS":                       "IMPRESSIONS",
    "AD_RECALL_LIFT":                    "IMPRESSIONS",
    "THRUPLAY":                          "THRUPLAY",
    "TWO_SECOND_CONTINUOUS_VIDEO_VIEWS": "IMPRESSIONS",
    "LINK_CLICKS":                       "LINK_CLICKS",
    "LANDING_PAGE_VIEWS":                "IMPRESSIONS",
    "CONVERSATIONS":                     "IMPRESSIONS",
    "VISIT_INSTAGRAM_PROFILE":           "IMPRESSIONS",
    "QUALITY_CALL":                      "IMPRESSIONS",
    "POST_ENGAGEMENT":                   "IMPRESSIONS",
    "EVENT_RESPONSES":                   "IMPRESSIONS",
    "OFFSITE_CONVERSIONS":               "IMPRESSIONS",
    "REMINDERS_SET":                     "IMPRESSIONS",
    "PAGE_LIKES":                        "PAGE_LIKES",
    "LEAD_GENERATION":                   "IMPRESSIONS",
    "QUALITY_LEAD":                      "IMPRESSIONS",
    "APP_INSTALLS":                      "IMPRESSIONS",
    "VALUE":                             "IMPRESSIONS",
}


@frappe.whitelist()
def get_performance_goals_for_objective(campaign):
    """
    Fetches the campaign objective from the Marketing Campaign doc
    and returns the allowed performance goal options for that objective.
    Called from ad_set.js via frappe.call.
    """
    objective = frappe.db.get_value(
        "Marketing Campaign", campaign, "custom_campaign_objective"
    )
    if not objective:
        frappe.throw(f"Campaign '{campaign}' has no objective set.")

    goals = OBJECTIVE_TO_PERFORMANCE_GOALS.get(objective, [])
    return {"objective": objective, "goals": goals}
