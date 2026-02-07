# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import getdate, add_days, nowdate


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    chart = get_chart(data)
    summary = get_summary(filters)
    
    return columns, data, None, chart, summary


def get_columns():
    return [
        {
            "fieldname": "platform",
            "label": _("Platform"),
            "fieldtype": "Data",
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
            "fieldname": "total_posts",
            "label": _("Total Posts"),
            "fieldtype": "Int",
            "width": 100
        },
        {
            "fieldname": "published",
            "label": _("Published"),
            "fieldtype": "Int",
            "width": 100
        },
        {
            "fieldname": "scheduled",
            "label": _("Scheduled"),
            "fieldtype": "Int",
            "width": 100
        },
        {
            "fieldname": "failed",
            "label": _("Failed"),
            "fieldtype": "Int",
            "width": 80
        },
        {
            "fieldname": "draft",
            "label": _("Draft"),
            "fieldtype": "Int",
            "width": 80
        },
        {
            "fieldname": "success_rate",
            "label": _("Success Rate %"),
            "fieldtype": "Percent",
            "width": 120
        },
        {
            "fieldname": "avg_retry_count",
            "label": _("Avg Retries"),
            "fieldtype": "Float",
            "precision": 1,
            "width": 100
        }
    ]


def get_data(filters):
    conditions = get_conditions(filters)
    
    data = frappe.db.sql("""
        SELECT 
            spp.platform,
            spp.integration,
            COUNT(DISTINCT sp.name) as total_posts,
            SUM(CASE WHEN sp.status = 'Published' THEN 1 ELSE 0 END) as published,
            SUM(CASE WHEN sp.status = 'Scheduled' THEN 1 ELSE 0 END) as scheduled,
            SUM(CASE WHEN sp.status = 'Failed' THEN 1 ELSE 0 END) as failed,
            SUM(CASE WHEN sp.status = 'Draft' THEN 1 ELSE 0 END) as draft,
            ROUND(
                SUM(CASE WHEN sp.status = 'Published' THEN 1 ELSE 0 END) * 100.0 / 
                NULLIF(SUM(CASE WHEN sp.status IN ('Published', 'Failed') THEN 1 ELSE 0 END), 0),
                1
            ) as success_rate,
            ROUND(AVG(sp.retry_count), 1) as avg_retry_count
        FROM `tabSocial Post` sp
        INNER JOIN `tabSocial Post Platform` spp ON spp.parent = sp.name
        WHERE 1=1
        {conditions}
        GROUP BY spp.platform, spp.integration
        ORDER BY total_posts DESC
    """.format(conditions=conditions), filters, as_dict=1)
    
    return data


def get_conditions(filters):
    conditions = []
    
    if filters.get("platform"):
        conditions.append("AND spp.platform = %(platform)s")
    
    if filters.get("integration"):
        conditions.append("AND spp.integration = %(integration)s")
    
    if filters.get("from_date"):
        conditions.append("AND sp.creation >= %(from_date)s")
    
    if filters.get("to_date"):
        conditions.append("AND sp.creation <= %(to_date)s")
    
    return " ".join(conditions)


def get_chart(data):
    if not data:
        return None
    
    # Aggregate by platform
    platforms = {}
    for row in data:
        platform = row.get("platform") or "Unknown"
        if platform not in platforms:
            platforms[platform] = {"published": 0, "scheduled": 0, "failed": 0, "draft": 0}
        platforms[platform]["published"] += row.get("published") or 0
        platforms[platform]["scheduled"] += row.get("scheduled") or 0
        platforms[platform]["failed"] += row.get("failed") or 0
        platforms[platform]["draft"] += row.get("draft") or 0
    
    return {
        "data": {
            "labels": list(platforms.keys()),
            "datasets": [
                {
                    "name": "Published",
                    "values": [p["published"] for p in platforms.values()]
                },
                {
                    "name": "Scheduled",
                    "values": [p["scheduled"] for p in platforms.values()]
                },
                {
                    "name": "Failed",
                    "values": [p["failed"] for p in platforms.values()]
                }
            ]
        },
        "type": "bar",
        "colors": ["#28a745", "#ffc107", "#dc3545"],
        "barOptions": {
            "stacked": True
        }
    }


def get_summary(filters):
    conditions = []
    
    if filters.get("from_date"):
        conditions.append("AND creation >= %(from_date)s")
    if filters.get("to_date"):
        conditions.append("AND creation <= %(to_date)s")
    
    condition_str = " ".join(conditions)
    
    stats = frappe.db.sql("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'Published' THEN 1 ELSE 0 END) as published,
            SUM(CASE WHEN status = 'Scheduled' THEN 1 ELSE 0 END) as scheduled,
            SUM(CASE WHEN status = 'Failed' THEN 1 ELSE 0 END) as failed,
            SUM(CASE WHEN status = 'Draft' AND docstatus = 0 THEN 1 ELSE 0 END) as draft
        FROM `tabSocial Post`
        WHERE 1=1 {conditions}
    """.format(conditions=condition_str), filters, as_dict=1)[0]
    
    total = stats.get("total") or 0
    published = stats.get("published") or 0
    scheduled = stats.get("scheduled") or 0
    failed = stats.get("failed") or 0
    draft = stats.get("draft") or 0
    
    attempted = published + failed
    success_rate = (published / attempted * 100) if attempted > 0 else 0
    
    return [
        {"value": total, "label": _("Total Posts"), "datatype": "Int"},
        {"value": published, "label": _("Published"), "datatype": "Int", "indicator": "green"},
        {"value": scheduled, "label": _("Scheduled"), "datatype": "Int", "indicator": "blue"},
        {"value": failed, "label": _("Failed"), "datatype": "Int", "indicator": "red" if failed > 0 else "grey"},
        {"value": round(success_rate, 1), "label": _("Success Rate %"), "datatype": "Percent", "indicator": "green" if success_rate >= 90 else "orange"}
    ]
