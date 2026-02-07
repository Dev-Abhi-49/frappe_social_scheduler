// Copyright (c) 2026, Frappe Social and contributors
// For license information, please see license.txt

frappe.ui.form.on('Social Analytics', {
    refresh: function(frm) {
        // Add link to integration
        if (frm.doc.integration) {
            frm.add_custom_button(__('View Integration'), function() {
                frappe.set_route('Form', 'Social Integration', frm.doc.integration);
            });
        }
        
        // Show engagement rate prominently
        if (frm.doc.engagement_rate) {
            frm.dashboard.add_indicator(
                __('Engagement Rate: {0}%', [frm.doc.engagement_rate]),
                frm.doc.engagement_rate > 3 ? 'green' : (frm.doc.engagement_rate > 1 ? 'blue' : 'grey')
            );
        }
    }
});
