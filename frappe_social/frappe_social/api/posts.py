"""
Posts API for Frappe Social Media Scheduler
"""

import frappe
from frappe import _
from frappe.utils import now_datetime, get_datetime
from frappe_social.frappe_social.services.post_service import PostService
from frappe_social.frappe_social.providers import get_provider

@frappe.whitelist()
def publish_now(post_name: str) -> dict:
    """Publish a post immediately"""
    post = frappe.get_doc("Social Post", post_name)

    if post.status not in ["Draft", "Scheduled", "Failed", "Cancelled"]:
        frappe.throw(_("Cannot publish post with status '{0}'").format(post.status))

    if post.docstatus == 0 or post.docstatus == 2:
        post.scheduled_time = now_datetime()
        post.submit()
        frappe.db.commit()
    else:
        post.db_set("scheduled_time", now_datetime())

    return PostService.publish_post(post_name)


@frappe.whitelist()
def schedule(post_name: str, scheduled_time: str) -> dict:
    """Schedule (or Reschedule) a post"""
    post = frappe.get_doc("Social Post", post_name)

    if post.status not in ["Draft", "Scheduled", "Failed", "Cancelled"]:
        frappe.throw(_("Cannot schedule post with status '{0}'").format(post.status))

    scheduled_dt = get_datetime(scheduled_time)
    if scheduled_dt <= now_datetime():
        frappe.throw(_("Scheduled time must be in the future"))

    post.scheduled_time = scheduled_dt
    post.status = "Scheduled"

    if post.docstatus == 0:
        post.submit()
    else:
        post.save()
    frappe.db.commit()

    return {"success": True, "scheduled_time": str(post.scheduled_time)}


@frappe.whitelist()
def cancel(post_name: str) -> dict:
    """Cancel a scheduled post"""
    return PostService.cancel_scheduled_post(post_name)

@frappe.whitelist()
def validate_content(content: str, platforms: list) -> dict:
    """Validate content against platform limits"""

    if isinstance(platforms, str):
        platforms = frappe.parse_json(platforms)

    errors, warnings = [], []
    content_len = len(content or "")

    for platform in platforms:
        try:
            max_len = get_provider(platform).MAX_CONTENT_LENGTH
            if content_len > max_len:
                errors.append(f"{platform}: Exceeds {max_len} chars")
            elif content_len > max_len * 0.9:
                warnings.append(f"{platform}: Near limit ({content_len}/{max_len})")
        except:
            pass

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}
