// Copyright (c) 2026, Abhishek and contributors
frappe.ui.form.on('Audience', {

    refresh(frm) {
        if (frm.doc.audience_id) {
            frm.set_df_property('audience_id', 'description',
                `✓ Created on Meta: ${frm.doc.audience_id}`);

            // Manual button to re-upload CRM data to existing audience
            if (frm.doc.subtype === 'CUSTOM') {
                frm.add_custom_button(__('Re-upload Customer List'), () => {
                    frappe.confirm(
                        __('This will re-upload the customer list to Meta. Continue?'),
                        () => {
                            frappe.call({
                                method: 'frappe_social.ads_manager.doctype.audience.audience.reupload_crm_users',
                                args: { docname: frm.doc.name },
                                callback: r => frappe.show_alert({
                                    message: r.message || 'Done',
                                    indicator: 'green'
                                })
                            });
                        }
                    );
                });
            }
        }
    },

    subtype(frm) {
        // Clear type-specific fields when switching audience type
        frm.set_value('pixel_id', '');
        frm.set_value('pixel_event', '');
        frm.set_value('application_id', '');
        frm.set_value('app_event', '');
        frm.set_value('engagement_source_id', '');
        frm.set_value('crm_data', '');
        frm.set_value('origin_audience_id', '');
        frm.refresh_fields();
    },

    origin_audience_id(frm) {
        // Auto-fill ad account from source audience for Lookalike
        if (frm.doc.subtype === 'LOOKALIKE' && frm.doc.origin_audience_id) {
            frappe.call({
                method: 'frappe.client.get_value',
                args: {
                    doctype: 'Audience',
                    filters: { name: frm.doc.origin_audience_id },
                    fieldname: 'select_ad_account'
                },
                callback: r => {
                    if (r.message?.select_ad_account && !frm.doc.select_ad_account) {
                        frm.set_value('select_ad_account', r.message.select_ad_account);
                    }
                }
            });
        }
    },

    validate(frm) {
        if (!frm.doc.audience_name) frappe.throw(__('Audience Name is required'));
        if (!frm.doc.select_ad_account) frappe.throw(__('Ad Account is required'));
        if (!frm.doc.subtype) frappe.throw(__('Audience Type is required'));

        if (frm.doc.subtype === 'LOOKALIKE') {
            const ratio = parseFloat(frm.doc.lookalike_ratio);
            if (isNaN(ratio) || ratio < 0.01 || ratio > 0.20) {
                frappe.throw(__('Lookalike ratio must be between 0.01 (1%) and 0.20 (20%)'));
            }
        }
        if (frm.doc.subtype === 'CUSTOM' && !frm.doc.crm_data) {
            frappe.throw(__('Customer data is required for Customer List audience'));
        }
    },

    before_save(frm) {
        if (frm.is_new()) {
            frappe.show_alert({ message: __('Creating audience on Meta...'), indicator: 'blue' });
        }
    }
});
