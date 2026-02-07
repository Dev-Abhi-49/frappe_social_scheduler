// Copyright (c) 2026, Frappe and contributors
// For license information, please see license.txt

frappe.query_reports["Post Performance"] = {
    "filters": [
        {
            "fieldname": "platform",
            "label": __("Platform"),
            "fieldtype": "Select",
            "options": "\nTwitter\nLinkedIn\nInstagram\nFacebook\nYouTube"
        },
        {
            "fieldname": "integration",
            "label": __("Account"),
            "fieldtype": "Link",
            "options": "Social Integration"
        },
        {
            "fieldname": "status",
            "label": __("Status"),
            "fieldtype": "Select",
            "options": "\nPublished\nScheduled\nFailed\nPartially Published"
        },
        {
            "fieldname": "from_date",
            "label": __("From Date"),
            "fieldtype": "Date",
            "default": frappe.datetime.add_months(frappe.datetime.get_today(), -1)
        },
        {
            "fieldname": "to_date",
            "label": __("To Date"),
            "fieldtype": "Date",
            "default": frappe.datetime.get_today()
        }
    ]
};
