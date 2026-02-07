# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    chart = get_chart(data)
    summary = get_summary(data)
    
    return columns, data, None, chart, summary


def get_columns():
    return [
        {
            "fieldname": "post_name",
            "label": _("Post"),
            "fieldtype": "Link",
            "options": "Social Post",
            "width": 120
        },
        {
            "fieldname": "content_preview",
            "label": _("Content"),
            "fieldtype": "Data",
            "width": 250
        },
        {
            "fieldname": "platform",
            "label": _("Platform"),
            "fieldtype": "Data",
            "width": 100
        },
        {
            "fieldname": "integration",
            "label": _("Account"),
            "fieldtype": "Link",
            "options": "Social Integration",
            "width": 150
        },
        {
            "fieldname": "status",
            "label": _("Status"),
            "fieldtype": "Data",
            "width": 100
        },
        {
            "fieldname": "published_time",
            "label": _("Published"),
            "fieldtype": "Datetime",
            "width": 150
        },
        {
            "fieldname": "impressions",
            "label": _("Impressions"),
            "fieldtype": "Int",
            "width": 100
        },
        {
            "fieldname": "reach",
            "label": _("Reach"),
            "fieldtype": "Int",
            "width": 80
        },
        {
            "fieldname": "likes",
            "label": _("Likes"),
            "fieldtype": "Int",
            "width": 70
        },
        {
            "fieldname": "comments",
            "label": _("Comments"),
            "fieldtype": "Int",
            "width": 80
        },
        {
            "fieldname": "shares",
            "label": _("Shares"),
            "fieldtype": "Int",
            "width": 70
        },
        {
            "fieldname": "engagement_rate",
            "label": _("Engagement %"),
            "fieldtype": "Percent",
            "width": 110
        }
    ]


def get_data(filters):
    conditions = get_conditions(filters)
    
    data = frappe.db.sql("""
        SELECT 
            sp.name as post_name,
            SUBSTRING(REGEXP_REPLACE(sp.content, '<[^>]+>', ''), 1, 80) as content_preview,
            spp.platform,
            spp.integration,
            sp.status,
            sp.published_time,
            COALESCE(spa.impressions, 0) as impressions,
            COALESCE(spa.reach, 0) as reach,
            COALESCE(spa.likes, 0) as likes,
            COALESCE(spa.comments, 0) as comments,
            COALESCE(spa.shares, 0) as shares,
            COALESCE(spa.engagement_rate, 0) as engagement_rate
        FROM `tabSocial Post` sp
        INNER JOIN `tabSocial Post Platform` spp ON spp.parent = sp.name
        LEFT JOIN `tabSocial Post Analytics` spa ON spa.social_post = sp.name 
            AND spa.platform = spp.platform
        WHERE sp.docstatus = 1
        {conditions}
        ORDER BY sp.published_time DESC, sp.creation DESC
    """.format(conditions=conditions), filters, as_dict=1)
    
    return data


def get_conditions(filters):
    conditions = []
    
    if filters.get("platform"):
        conditions.append("AND spp.platform = %(platform)s")
    
    if filters.get("integration"):
        conditions.append("AND spp.integration = %(integration)s")
    
    if filters.get("status"):
        conditions.append("AND sp.status = %(status)s")
    
    if filters.get("from_date"):
        conditions.append("AND sp.published_time >= %(from_date)s")
    
    if filters.get("to_date"):
        conditions.append("AND sp.published_time <= %(to_date)s")
    
    return " ".join(conditions)


def get_chart(data):
    if not data:
        return None
    
    platforms = {}
    for row in data:
        platform = row.get("platform") or "Unknown"
        if platform not in platforms:
            platforms[platform] = {"impressions": 0, "engagement": 0, "count": 0}
        platforms[platform]["impressions"] += row.get("impressions") or 0
        platforms[platform]["engagement"] += row.get("likes", 0) + row.get("comments", 0) + row.get("shares", 0)
        platforms[platform]["count"] += 1
    
    return {
        "data": {
            "labels": list(platforms.keys()),
            "datasets": [
                {
                    "name": "Impressions",
                    "values": [p["impressions"] for p in platforms.values()]
                },
                {
                    "name": "Engagements",
                    "values": [p["engagement"] for p in platforms.values()]
                }
            ]
        },
        "type": "bar",
        "colors": ["#7cd6fd", "#5e64ff"]
    }


def get_summary(data):
    if not data:
        return []
    
    total_impressions = sum(row.get("impressions") or 0 for row in data)
    total_reach = sum(row.get("reach") or 0 for row in data)
    total_likes = sum(row.get("likes") or 0 for row in data)
    total_comments = sum(row.get("comments") or 0 for row in data)
    total_shares = sum(row.get("shares") or 0 for row in data)
    total_posts = len(data)
    
    avg_engagement = sum(row.get("engagement_rate") or 0 for row in data) / total_posts if total_posts else 0
    
    return [
        {"value": total_posts, "label": _("Total Posts"), "datatype": "Int"},
        {"value": total_impressions, "label": _("Total Impressions"), "datatype": "Int"},
        {"value": total_reach, "label": _("Total Reach"), "datatype": "Int"},
        {"value": total_likes + total_comments + total_shares, "label": _("Total Engagements"), "datatype": "Int"},
        {"value": round(avg_engagement, 2), "label": _("Avg Engagement %"), "datatype": "Percent"}
    ]
