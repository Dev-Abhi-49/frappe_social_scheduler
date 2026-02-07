// Copyright (c) 2026, Abhishek and contributors
// For license information, please see license.txt

frappe.ui.form.on('Ad Set', {
    refresh(frm) {
        // Show adset ID info if already created
        if (frm.doc.adset_id) {
            frm.set_df_property('adset_id', 'description',
                `✓ Ad Set created on Meta: ${frm.doc.adset_id}`);
        }
        
        // Disable adset_id field
        frm.set_df_property('adset_id', 'read_only', 1);
        
        // Load Facebook pages if campaign is already selected (on reload)
        if (frm.doc.campaign) {
            load_facebook_pages(frm);
        }
    },
    
    onload(frm) {
        // Set filter for campaign field to show only Meta Ads campaigns
        frm.set_query('campaign', function() {
            return {
                filters: {
                    'custom_is_meta_ads': 1
                }
            };
        });
    },
    
    campaign(frm) {
        // When campaign is selected, fetch and populate Facebook pages
        if (frm.doc.campaign) {
            load_facebook_pages(frm);
        }
    },
    
    validate(frm) {
        // Validate required fields
        if (!frm.doc.campaign) {
            frappe.throw(__('Please select a Campaign'));
        }
        
        if (!frm.doc.ad_set_name) {
            frappe.throw(__('Ad Set Name is required'));
        }
        
        if (!frm.doc.billing_event) {
            frappe.throw(__('Billing Event is required'));
        }
        
        if (!frm.doc.daily_budget) {
            frappe.throw(__('Daily Budget is required'));
        }
    },
    
    before_save(frm) {
        if (frm.is_new()) {
            frappe.show_alert({
                message: __('Creating ad set on Meta Ads...'),
                indicator: 'blue'
            });
        }
    }
});

// Helper function to load Facebook pages
function load_facebook_pages(frm) {
    frappe.call({
        method: 'frappe.client.get',
        args: {
            doctype: 'Marketing Campaign',
            name: frm.doc.campaign
        },
        callback: function(r) {
            if (r.message && r.message.custom_select_facebook_ad_account) {
                // Get the Ads Account Integration document
                frappe.call({
                    method: 'frappe.client.get',
                    args: {
                        doctype: 'Ads Account Integration',
                        name: r.message.custom_select_facebook_ad_account,
                        fields: ['fb_pages']
                    },
                    callback: function(res) {
                        if (res.message && res.message.fb_pages && res.message.fb_pages.length > 0) {
                            // Build options for select field
                            let page_options = res.message.fb_pages.map(page => page.page_name);
                            
                            // Update the select field options
                            frm.set_df_property('select_facebook_page', 'options', page_options.join('\n'));
                            
                            frappe.show_alert({
                                message: __(`${page_options.length} Facebook page(s) loaded`),
                                indicator: 'green'
                            });
                        } else {
                            frappe.msgprint({
                                title: __('No Facebook Pages'),
                                indicator: 'orange',
                                message: __('No Facebook pages found for this ad account. Please sync your account.')
                            });
                            
                            // Clear the field
                            frm.set_df_property('select_facebook_page', 'options', '');
                        }
                    }
                });
            } else {
                frappe.msgprint({
                    title: __('Invalid Campaign'),
                    indicator: 'red',
                    message: __('Selected campaign does not have an associated Facebook ad account.')
                });
            }
        }
    });
}
