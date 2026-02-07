# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, add_days


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    chart = get_chart(data, filters)
    summary = get_summary(data)
    
    return columns, data, None, chart, summary


def get_columns():
    return [
        {
            "fieldname": "date",
            "label": _("Date"),
            "fieldtype": "Date",
            "width": 120
        },
        {
            "fieldname": "integration",
            "label": _("Account"),
            "fieldtype": "Link",
            "options": "Social Integration",
            "width": 180
        },
        {
            "fieldname": "platform",
            "label": _("Platform"),
            "fieldtype": "Data",
            "width": 100
        },
        {
            "fieldname": "followers_count",
            "label": _("Followers"),
            "fieldtype": "Int",
            "width": 100
        },
        {
            "fieldname": "followers_gained",
            "label": _("Gained"),
            "fieldtype": "Int",
            "width": 80
        },
        {
            "fieldname": "followers_lost",
            "label": _("Lost"),
            "fieldtype": "Int",
            "width": 80
        },
        {
            "fieldname": "net_change",
            "label": _("Net Change"),
            "fieldtype": "Int",
            "width": 100
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
            "width": 90
        },
        {
            "fieldname": "engagement_rate",
            "label": _("Engagement %"),
            "fieldtype": "Percent",
            "width": 110
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
        }
    ]


def get_data(filters):
    conditions = get_conditions(filters)
    
    data = frappe.db.sql("""
        SELECT 
            sa.date,
            sa.integration,
            sa.platform,
            sa.followers_count,
            sa.followers_gained,
            sa.followers_lost,
            (COALESCE(sa.followers_gained, 0) - COALESCE(sa.followers_lost, 0)) as net_change,
            sa.impressions,
            sa.reach,
            sa.engagement_rate,
            sa.likes,
            sa.comments,
            sa.shares
        FROM `tabSocial Analytics` sa
        WHERE 1=1
        {conditions}
        ORDER BY sa.date DESC, sa.integration
    """.format(conditions=conditions), filters, as_dict=1)
    
    return data


def get_conditions(filters):
    conditions = []
    
    if filters.get("platform"):
        conditions.append("AND sa.platform = %(platform)s")
    
    if filters.get("integration"):
        conditions.append("AND sa.integration = %(integration)s")
    
    if filters.get("from_date"):
        conditions.append("AND sa.date >= %(from_date)s")
    
    if filters.get("to_date"):
        conditions.append("AND sa.date <= %(to_date)s")
    
    return " ".join(conditions)


def get_chart(data, filters):
    if not data:
        return None
    
    # Group by date for chart
    date_data = {}
    for row in data:
        date_str = str(row.get("date"))
        if date_str not in date_data:
            date_data[date_str] = {
                "followers": 0,
                "impressions": 0,
                "engagement": 0,
                "count": 0
            }
        date_data[date_str]["followers"] += row.get("followers_count") or 0
        date_data[date_str]["impressions"] += row.get("impressions") or 0
        date_data[date_str]["engagement"] += row.get("likes", 0) + row.get("comments", 0) + row.get("shares", 0)
        date_data[date_str]["count"] += 1
    
    # Sort by date
    sorted_dates = sorted(date_data.keys())
    
    return {
        "data": {
            "labels": sorted_dates[-30:],  # Last 30 days
            "datasets": [
                {
                    "name": "Followers",
                    "values": [date_data[d]["followers"] for d in sorted_dates[-30:]]
                },
                {
                    "name": "Impressions",
                    "values": [date_data[d]["impressions"] for d in sorted_dates[-30:]]
                }
            ]
        },
        "type": "line",
        "colors": ["#5e64ff", "#7cd6fd"]
    }


def get_summary(data):
    if not data:
        return []
    
    # Get latest follower count per integration
    latest_followers = {}
    total_impressions = 0
    total_reach = 0
    total_engagement = 0
    
    for row in data:
        integration = row.get("integration")
        if integration not in latest_followers:
            latest_followers[integration] = row.get("followers_count") or 0
        total_impressions += row.get("impressions") or 0
        total_reach += row.get("reach") or 0
        total_engagement += (row.get("likes") or 0) + (row.get("comments") or 0) + (row.get("shares") or 0)
    
    total_followers = sum(latest_followers.values())
    total_net_change = sum(row.get("net_change") or 0 for row in data)
    num_accounts = len(latest_followers)
    
    return [
        {"value": num_accounts, "label": _("Accounts"), "datatype": "Int"},
        {"value": total_followers, "label": _("Total Followers"), "datatype": "Int"},
        {"value": total_net_change, "label": _("Net Growth"), "datatype": "Int", "indicator": "green" if total_net_change > 0 else "red"},
        {"value": total_impressions, "label": _("Total Impressions"), "datatype": "Int"},
        {"value": total_engagement, "label": _("Total Engagements"), "datatype": "Int"}
    ]
