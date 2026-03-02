// Copyright (c) 2026, Abhishek and contributors
// For license information, please see license.txt

// =====================================================
// FORM VIEW - Post Ads
// =====================================================

frappe.ui.form.on('Post Ads', {
    refresh(frm) {
        frm.dashboard.clear_headline();

        // Set headline message
        frm.dashboard.set_headline(`
            <div style="color: #e4a63cff; font-weight: 600; font-size: 14px; text-align: center;">
                📱 Meta Ad Manager - Create and manage Facebook/Instagram ads
            </div>
        `);

        // Apply filters to link fields
        apply_field_filters(frm);

        // Update UI based on status
        update_ad_buttons(frm);
        update_status_indicator(frm);
    },

    // =====================================================
    // FIELD CHANGE EVENTS
    // =====================================================

    campaign(frm) {
        // Reset dependent fields
        frm.set_value('select_ad_set', '');
        apply_field_filters(frm);
    },

    select_ad_set(frm) {
        apply_field_filters(frm);
    },

    enable_ad(frm) {
        if (frm.doc.enable_ad) {
            frappe.msgprint({
                title: __('Ad Enabled'),
                message: __('This ad is now enabled for publishing to Meta.'),
                indicator: 'blue'
            });
        }
    },

    partnership_ad(frm) {
        if (frm.doc.partnership_ad) {
            frappe.msgprint({
                title: __('Partnership Ad'),
                message: __('This ad is marked as a partnership ad.'),
                indicator: 'blue'
            });
        }
    },

    schedule_time(frm) {
        validate_schedule_time(frm);
    }
});

// =====================================================
// FORM ACTIONS / BUTTONS
// =====================================================

function add_publish_button(frm) {
    frm.add_custom_button(__('Publish'), function () {
        if (!frm.doc.enable_ad) {
            frappe.msgprint(__('Please enable the ad first'));
            return;
        }

        if (!frm.doc.id) {
            frappe.confirm(
                __('Publish this ad to Meta now?'),
                () => {
                    frappe.call({
                        method: 'frappe_social.ads_manager.doctype.post_ads.post_ads.publish_ad',
                        args: { post_ads_name: frm.doc.name },
                        freeze: true,
                        freeze_message: __('Publishing to Meta...'),
                        callback: function (r) {
                            if (r.message && r.message.success) {
                                frappe.msgprint({
                                    title: __('Success'),
                                    message: r.message.message,
                                    indicator: 'green'
                                });
                                frm.reload_doc();
                            } else {
                                frappe.msgprint({
                                    title: __('Error'),
                                    message: r.message ? r.message.message : __('Failed to publish'),
                                    indicator: 'red'
                                });
                            }
                        }
                    });
                }
            );
        }
    }, __('Actions'));
}

function add_pause_button(frm) {
    frm.add_custom_button(__('Pause'), function () {
        if (!frm.doc.id) {
            frappe.msgprint(__('Ad not published yet'));
            return;
        }

        frappe.confirm(__('Pause this ad?'), () => {
            frappe.call({
                method: 'frappe_social.ads_manager.doctype.post_ads.post_ads.pause_ad',
                args: { post_ads_name: frm.doc.name },
                freeze: true,
                callback: function (r) {
                    if (r.message && r.message.success) {
                        frappe.toast(__('Ad paused'));
                        frm.reload_doc();
                    } else {
                        frappe.msgprint(__('Error pausing ad'));
                    }
                }
            });
        });
    }, __('Actions'));
}

function add_resume_button(frm) {
    frm.add_custom_button(__('Resume'), function () {
        if (!frm.doc.id) {
            frappe.msgprint(__('Ad not published yet'));
            return;
        }

        frappe.confirm(__('Resume this ad?'), () => {
            frappe.call({
                method: 'frappe_social.ads_manager.doctype.post_ads.post_ads.resume_ad',
                args: { post_ads_name: frm.doc.name },
                freeze: true,
                callback: function (r) {
                    if (r.message && r.message.success) {
                        frappe.toast(__('Ad resumed'));
                        frm.reload_doc();
                    } else {
                        frappe.msgprint(__('Error resuming ad'));
                    }
                }
            });
        });
    }, __('Actions'));
}

function add_analytics_button(frm) {
    frm.add_custom_button(__('View Analytics'), function () {
        if (!frm.doc.id) {
            frappe.msgprint(__('Ad not published yet'));
            return;
        }

        frappe.call({
            method: 'frappe_social.ads_manager.doctype.post_ads.post_ads.get_ad_analytics',
            args: { post_ads_name: frm.doc.name },
            freeze: true,
            freeze_message: __('Loading analytics...'),
            callback: function (r) {
                if (r.message && r.message.success) {
                    show_analytics_dialog(r.message.metrics);
                } else {
                    frappe.msgprint(__('No analytics data available yet'));
                }
            }
        });
    });
}

// =====================================================
// HELPER FUNCTIONS
// =====================================================

function apply_field_filters(frm) {
    // Filter: select_ad_set by campaign
    if (frm.doc.campaign) {
        frm.set_query('select_ad_set', () => ({
            filters: {
                'campaign': frm.doc.campaign
            }
        }));
    } else {
        frm.set_query('select_ad_set', () => ({
            filters: { name: ['in', []] }
        }));
    }

    // Filter: select_ad_creative (all active creatives)
    frm.set_query('select_ad_creative', () => ({
        filters: {
            'docstatus': 0
        }
    }));
}

function update_ad_buttons(frm) {
    // Clear all custom buttons
    frm.clear_custom_buttons();

    if (frm.is_new()) {
        return;
    }

    if (!frm.doc.id) {
        // Ad not yet published
        if (frm.doc.enable_ad) {
            add_publish_button(frm);
        }
    } else {
        // Ad is published
        if (frm.doc.status === 'ACTIVE') {
            add_pause_button(frm);
            add_analytics_button(frm);
        } else if (frm.doc.status === 'PAUSED') {
            add_resume_button(frm);
            add_analytics_button(frm);
        } else {
            add_analytics_button(frm);
        }
    }
}

function update_status_indicator(frm) {
    let indicator = 'grey';

    switch (frm.doc.status) {
        case 'ACTIVE':
            indicator = 'green';
            break;
        case 'PAUSED':
            indicator = 'orange';
            break;
        case 'DELETED':
            indicator = 'red';
            break;
        case 'ARCHIVED':
            indicator = 'red';
            break;
    }

    frm.page.set_indicator(frm.doc.status || 'DRAFT', indicator);
}

function validate_schedule_time(frm) {
    if (!frm.doc.schedule_time) return;

    const scheduled = moment(frm.doc.schedule_time);
    const now = moment();

    if (scheduled.isBefore(now)) {
        frappe.msgprint({
            title: __('Invalid Schedule Time'),
            message: __('Schedule time must be in the future'),
            indicator: 'red'
        });
        frm.set_value('schedule_time', null);
    }
}

function show_analytics_dialog(metrics) {
    if (!metrics) {
        frappe.msgprint({
            title: __('No Data'),
            message: __('No analytics data available for this ad.'),
            indicator: 'orange'
        });
        return;
    }

    const html = `
        <table class="table table-bordered">
            <tr style="background-color: #f5f5f5;">
                <th>${__('Metric')}</th>
                <th style="text-align: right;">${__('Value')}</th>
            </tr>
            <tr>
                <td><strong>${__('Spend')}</strong></td>
                <td style="text-align: right;">₹${(metrics.spend || 0).toFixed(2)}</td>
            </tr>
            <tr>
                <td><strong>${__('Impressions')}</strong></td>
                <td style="text-align: right;">${(metrics.impressions || 0).toLocaleString()}</td>
            </tr>
            <tr>
                <td><strong>${__('Clicks')}</strong></td>
                <td style="text-align: right;">${(metrics.clicks || 0).toLocaleString()}</td>
            </tr>
            <tr>
                <td><strong>${__('CTR')}</strong></td>
                <td style="text-align: right;">${(metrics.ctr || 0).toFixed(2)}%</td>
            </tr>
            <tr>
                <td><strong>${__('CPC')}</strong></td>
                <td style="text-align: right;">₹${(metrics.cpc || 0).toFixed(2)}</td>
            </tr>
            <tr>
                <td><strong>${__('Reach')}</strong></td>
                <td style="text-align: right;">${(metrics.reach || 0).toLocaleString()}</td>
            </tr>
            <tr>
                <td><strong>${__('Conversions')}</strong></td>
                <td style="text-align: right;">${(metrics.conversions || 0).toLocaleString()}</td>
            </tr>
            <tr>
                <td><strong>${__('Conversion Rate')}</strong></td>
                <td style="text-align: right;">${(metrics.conversion_rate || 0).toFixed(2)}%</td>
            </tr>
            <tr>
                <td><strong>${__('ROAS')}</strong></td>
                <td style="text-align: right;">${(metrics.purchase_roas || 0).toFixed(2)}x</td>
            </tr>
        </table>
    `;

    frappe.msgprint({
        title: __('Ad Analytics (Last 7 Days)'),
        message: html,
        indicator: 'blue',
        wide: true
    });
}

// =====================================================
// LIST VIEW - Post Ads
// =====================================================

frappe.listview_settings['Post Ads'] = {
    add_fields: ['status', 'enable_ad', 'id'],

    get_indicator(doc) {
        if (doc.status === 'ACTIVE') {
            return [__('Active'), 'green', 'status,=,ACTIVE'];
        } else if (doc.status === 'PAUSED') {
            return [__('Paused'), 'orange', 'status,=,PAUSED'];
        } else if (doc.status === 'DELETED') {
            return [__('Deleted'), 'red', 'status,=,DELETED'];
        } else if (doc.status === 'ARCHIVED') {
            return [__('Archived'), 'red', 'status,=,ARCHIVED'];
        }
        return [__('Unknown'), 'grey'];
    },

    onload(listview) {
        // Change primary action button
        listview.page.clear_primary_action();
        listview.page.set_primary_action(
            __('New Ad'),
            () => frappe.new_doc('Post Ads'),
            'add'
        );
    },

    refresh(listview) {
        // Re-apply primary action after refresh
        listview.page.clear_primary_action();
        listview.page.set_primary_action(
            __('New Ad'),
            () => frappe.new_doc('Post Ads'),
            'add'
        );
    }
};