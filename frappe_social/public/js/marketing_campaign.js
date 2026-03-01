frappe.ui.form.on('Marketing Campaign', {
    refresh: function (frm) {

        if (!frm.is_new()) {
            // Add "Create Campaign on Meta" button
            if (frm.doc.custom_is_meta_ads) {
                if (!frm.doc.custom_facebook_campaign_id) {
                    frm.add_custom_button(__('Create Campaign on Meta'), function () {
                        frm.trigger('create_campaign_on_meta');
                    }, __('Actions'));
                } else {
                    frm.add_custom_button(__('View Campaign on Meta'), function () {
                        const campaign_id = frm.doc.custom_facebook_campaign_id;
                        frappe.msgprint({
                            title: __('Meta Campaign Details'),
                            message: __('Campaign ID: <strong>{0}</strong><br><br><a href="https://business.facebook.com/ads/manager" target="_blank">View in Meta Ads Manager →</a>', [campaign_id]),
                            indicator: 'blue'
                        });
                    }, __('Actions'));
                }
            }

            frm.add_custom_button(__('Fetch Analytics'), function () {
                frm.trigger('fetch_analytics');
            }, __('Actions'));
        }
        toggle_ads_section_visibility(frm);
    },

    after_save: function (frm) {
        // Check if no ads are selected
        const any_ads_selected = frm.doc.custom_is_meta_ads ||
            frm.doc.custom_is_google_ads ||
            frm.doc.custom_is_linkedin_ads ||
            frm.doc.custom_is_twitter_ads;

        if (!any_ads_selected && !frm.is_new()) {
            // Reload the form to apply visibility changes
            frappe.set_route('Form', 'Marketing Campaign', frm.doc.name);
        } else {
            toggle_ads_section_visibility(frm);
        }
    },

    custom_is_meta_ads: function (frm) {
        toggle_ads_section_visibility(frm);
    },

    custom_is_google_ads: function (frm) {
        toggle_ads_section_visibility(frm);
    },

    custom_is_linkedin_ads: function (frm) {
        toggle_ads_section_visibility(frm);
    },

    custom_is_twitter_ads: function (frm) {
        toggle_ads_section_visibility(frm);
    },

    fetch_analytics: function (frm) {
        frappe.call({
            method: 'frappe_social.ads_manager.api.analytics.get_campaign_analytics',
            args: { integration: frm.doc.name },
            freeze: true,
            freeze_message: __('Fetching analytics from Meta...'),
            callback: function (r) {
                if (r.message) {
                    if (r.message.success) {
                        frappe.show_alert({
                            message: __('✓ Analytics fetched successfully!'),
                            indicator: 'green'
                        }, 3);

                        // Show detailed metrics in a dialog
                        if (r.message.metrics) {
                            show_analytics_summary(r.message.metrics, r.message.analytics_doc);
                        }
                    } else {
                        // No analytics available - show detailed message
                        const message = r.message.message || __('Analytics Not Available');
                        const details = r.message.details || r.message.error_message || __('No data available');

                        frappe.show_alert({
                            message: message,
                            indicator: 'orange'
                        }, 5);

                        // Show dialog with details
                        frappe.msgprint({
                            title: __('📊 No Campaign Analytics'),
                            message: details,
                            indicator: 'orange'
                        });
                    }
                }
            },
            error: function (err) {
                frappe.show_alert({
                    message: __('Error fetching analytics. Please try again.'),
                    indicator: 'red'
                });
                console.error(err);
            }
        });
    },

    create_campaign_on_meta: function (frm) {
        if (frm.is_new()) {
            frappe.throw(__('Please save the campaign before creating it on Meta.'));
        }

        frappe.call({
            method: 'frappe_social.ads_manager.script.campaign.create_campaign_on_meta',
            args: {
                campaign_name: frm.doc.name
            },
            freeze: true,
            freeze_message: __('Creating campaign on Meta...'),
            callback: function (r) {
                const response = r.message || {};

                if (response.success) {
                    const campaign_id = response.campaign_id || __('N/A');
                    frappe.show_alert({
                        message: __('✓ Campaign created on Meta. ID: {0}', [campaign_id]),
                        indicator: 'green'
                    }, 5);
                    frm.reload_doc();
                    return;
                }

                frappe.show_alert({
                    message: response.message || __('Campaign creation did not complete.'),
                    indicator: 'orange'
                }, 5);
            },
            error: function (err) {
                let error_message = __('Error creating campaign on Meta. Please try again.');

                const response_json = err && err.responseJSON ? err.responseJSON : null;
                const server_error = (err && err.message)
                    || (response_json && response_json.exception)
                    || (response_json && response_json.message);
                if (server_error) {
                    error_message = server_error;
                }

                frappe.msgprint({
                    title: __('Meta Campaign Creation Failed'),
                    message: error_message,
                    indicator: 'red'
                });

                frappe.show_alert({
                    message: __('Campaign creation failed.'),
                    indicator: 'red'
                }, 5);
            }
        });
    },
});

function toggle_ads_section_visibility(frm) {
    const any_ads_selected = frm.doc.custom_is_meta_ads ||
        frm.doc.custom_is_google_ads ||
        frm.doc.custom_is_linkedin_ads ||
        frm.doc.custom_is_twitter_ads;

    if (frm.is_new()) {
        show_ads_section(frm);
    } else {
        if (any_ads_selected) {
            show_ads_section(frm);
        } else {
            hide_ads_section(frm);
        }
    }
}

function show_ads_section(frm) {
    frm.set_df_property('custom_is_meta_ads', 'hidden', 0);
    frm.set_df_property('custom_is_google_ads', 'hidden', 0);
    frm.set_df_property('custom_is_linkedin_ads', 'hidden', 0);
    frm.set_df_property('custom_is_twitter_ads', 'hidden', 0);
}

function hide_ads_section(frm) {
    frm.set_df_property('custom_is_meta_ads', 'hidden', 1);
    frm.set_df_property('custom_is_google_ads', 'hidden', 1);
    frm.set_df_property('custom_is_linkedin_ads', 'hidden', 1);
    frm.set_df_property('custom_is_twitter_ads', 'hidden', 1);
}
