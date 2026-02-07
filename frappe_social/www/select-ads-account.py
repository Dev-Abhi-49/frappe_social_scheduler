import frappe

def get_context(context):
    # Require login
    if frappe.session.user == "Guest":
        frappe.throw("Please login to continue", frappe.AuthenticationError)

    context.no_cache = 1
    return context