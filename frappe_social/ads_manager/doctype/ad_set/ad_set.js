frappe.ui.form.on('Ad Set', {
    refresh: function (frm) {
        // Add "Create on Meta" button for saved but not yet created ad sets
        if (!frm.is_new()) {
            if (!frm.doc.adset_id) {
                frm.add_custom_button(__('Create on Meta'), function () {
                    frm.trigger('create_ad_set_on_meta');
                }, __('Actions'));
            } else {
                frm.add_custom_button(__('View on Meta'), function () {
                    const adset_id = frm.doc.adset_id;
                    frappe.msgprint({
                        title: __('Meta Ad Set Details'),
                        message: __('Ad Set ID: <strong>{0}</strong><br><br><a href="https://business.facebook.com/ads/manager" target="_blank">View in Meta Ads Manager →</a>', [adset_id]),
                        indicator: 'blue'
                    });
                }, __('Actions'));
            }

            frm.add_custom_button(__('Fetch Analytics'), function () {
                frm.trigger('fetch_ad_set_analytics');
            }, __('Actions'));
        }

        // Set campaign filter based on Meta Ads selection
        frm.set_df_property('campaign', 'filters', {
            'custom_is_meta_ads': 1
        });

        toggle_status_fields(frm);
        toggle_budget_section_visibility(frm);
    },

    campaign: function (frm) {
        /**
         * When campaign changes, update budget section visibility
         * based on campaign's CBO (Campaign Budget Optimization) setting
         */
        if (frm.doc.campaign) {
            frappe.call({
                method: 'frappe.client.get',
                args: {
                    doctype: 'Marketing Campaign',
                    name: frm.doc.campaign
                },
                callback: function (r) {
                    if (r.message) {
                        const campaign = r.message;
                        const has_cbo = campaign.custom_enable_adset_budget_sharing;

                        if (has_cbo) {
                            frappe.msgprint({
                                title: __('📊 Campaign Budget Optimization'),
                                message: __('This campaign has <b>CBO enabled</b>.<br>Budget is managed at campaign level.<br>Ad Set budget fields will be hidden.'),
                                indicator: 'blue'
                            });
                        } else {
                            frappe.msgprint({
                                title: __('💰 Ad Set Budget Required'),
                                message: __('This campaign has <b>CBO disabled</b>.<br>You must set the budget at Ad Set level.'),
                                indicator: 'orange'
                            });
                        }

                        toggle_budget_section_visibility(frm);
                    }
                }
            });
        }
    },

    before_save: function (frm) {
        console.log('[AdSet JS] Before save - is_new:', frm.is_new(), 'enable_ad_set:', frm.doc.enable_ad_set, 'adset_id:', frm.doc.adset_id);

        // If creating new ad set, validate required fields
        if (frm.is_new()) {
            console.log('[AdSet JS] Validating Ad Set creation fields...');

            if (!frm.doc.ad_set_name) {
                frappe.throw(__("Ad Set Name is required"));
            }
            if (!frm.doc.campaign) {
                frappe.throw(__("Campaign is required"));
            }
            if (!frm.doc.billing_event) {
                frappe.throw(__("Billing Event is required"));
            }
            if (!frm.doc.performance_goal) {
                frappe.throw(__("Optimization Goal is required"));
            }
            // if (!frm.doc.budget_type_dailylifetime) {
            //     frappe.throw(__("Budget Type is required"));
            // }

            // Validate budget only if campaign doesn't have CBO
            frappe.call({
                method: 'frappe.client.get',
                args: {
                    doctype: 'Marketing Campaign',
                    name: frm.doc.campaign
                },
                async: false,
                callback: function (r) {
                    if (r.message) {
                        const has_cbo = r.message.custom_enable_adset_budget_sharing;
                        if (!has_cbo && (!frm.doc.amount || frm.doc.amount <= 0)) {
                            frappe.throw(__("Ad Set Amount is required and must be greater than 0 (Campaign Budget Optimization is disabled)"));
                        }
                    }
                }
            });

            console.log('[AdSet JS] All validations passed, proceeding with Meta Ad Set creation...');
        }
    },

    after_save: function (frm) {
        console.log('[AdSet JS] After save - adset_id:', frm.doc.adset_id);
        if (frm.doc.adset_id) {
            frappe.show_alert({
                message: __('✅ Ad Set created on Meta! ID: ' + frm.doc.adset_id),
                indicator: 'green'
            }, 5);
        }
    },

    enable_ad_set: function (frm) {
        toggle_status_fields(frm);
    },

    create_ad_set_on_meta: function (frm) {
        /**
         * Create Ad Set on Meta without automatic Frappe save
         * Validates all required fields before sending to Meta
         */
        if (frm.is_new()) {
            frappe.throw(__('Please save the Ad Set in Frappe before creating it on Meta.'));
        }

        if (!frm.doc.campaign) {
            frappe.throw(__('Campaign is required'));
        }
        if (!frm.doc.ad_set_name) {
            frappe.throw(__('Ad Set Name is required'));
        }
        if (!frm.doc.billing_event) {
            frappe.throw(__('Billing Event is required'));
        }
        if (!frm.doc.performance_goal) {
            frappe.throw(__('Optimization Goal is required'));
        }

        // Validate budget based on campaign's CBO setting
        frappe.call({
            method: 'frappe.client.get',
            args: {
                doctype: 'Marketing Campaign',
                name: frm.doc.campaign
            },
            async: false,
            callback: function (r) {
                if (r.message) {
                    const has_cbo = r.message.custom_enable_adset_budget_sharing;
                    if (!has_cbo && (!frm.doc.amount || frm.doc.amount <= 0)) {
                        frappe.throw(__("Ad Set Amount is required and must be greater than 0 (Campaign Budget Optimization is disabled)"));
                    }
                }
            }
        });

        // Call backend to create on Meta
        frappe.call({
            method: 'frappe_social.ads_manager.doctype.ad_set.ad_set.create_ad_set_on_meta_async',
            args: {
                ad_set_name: frm.doc.name
            },
            freeze: true,
            freeze_message: __('Creating Ad Set on Meta...'),
            callback: function (r) {
                if (r.message) {
                    const response = r.message;

                    if (response.success) {
                        const adset_id = response.adset_id || __('N/A');
                        frappe.show_alert({
                            message: __('✅ Ad Set created on Meta! ID: ' + adset_id),
                            indicator: 'green'
                        }, 5);
                        // Reload the form to show the new adset_id
                        frm.reload_doc();
                        return;
                    }

                    frappe.show_alert({
                        message: response.message || __('Ad Set creation did not complete.'),
                        indicator: 'orange'
                    }, 5);

                    if (response.error_message) {
                        frappe.msgprint({
                            title: __('Meta Ad Set Creation Error'),
                            message: response.error_message,
                            indicator: 'orange'
                        });
                    }
                }
            },
            error: function (err) {
                let error_message = __('Error creating Ad Set on Meta. Please try again.');

                const response_json = err && err.responseJSON ? err.responseJSON : null;
                const server_error = (err && err.message)
                    || (response_json && response_json.exception)
                    || (response_json && response_json.message);

                if (server_error) {
                    error_message = server_error;
                }

                frappe.msgprint({
                    title: __('Meta Ad Set Creation Failed'),
                    message: error_message,
                    indicator: 'red'
                });

                frappe.show_alert({
                    message: __('Ad Set creation failed.'),
                    indicator: 'red'
                }, 5);
            }
        });
    },

    fetch_ad_set_analytics: function (frm) {
        if (!frm.doc.adset_id) {
            frappe.show_alert({
                message: __('Ad Set has not been created on Meta Ads yet'),
                indicator: 'orange'
            });
            return;
        }

        frappe.call({
            method: 'frappe_social.ads_manager.api.analytics.get_adset_analytics',
            args: { adset_id: frm.doc.name },
            freeze: true,
            freeze_message: __('Fetching analytics from Meta...'),
            callback: function (r) {
                if (r.message) {
                    if (r.message.success) {
                        frappe.show_alert({
                            message: __('✓ Analytics fetched successfully!'),
                            indicator: 'green'
                        }, 3);

                        if (r.message.metrics) {
                            show_adset_analytics_summary(r.message.metrics, r.message.analytics_doc);
                        }
                    } else {
                        const message = r.message.message || __('Analytics Not Available');
                        const details = r.message.details || r.message.error_message || __('No data available');

                        frappe.show_alert({
                            message: message,
                            indicator: 'orange'
                        }, 5);

                        frappe.msgprint({
                            title: __('📊 No Ad Set Analytics'),
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
    }
});

function show_adset_analytics_summary(metrics, analytics_doc) {
    /**
     * Display ad set analytics in a formatted dialog
     */
    const html = `
        <div style="padding: 20px;">
            <h5>📊 Ad Set Performance (Last 7 Days)</h5>
            
            <table style="width: 100%; border-collapse: collapse; margin: 15px 0;">
                <tr style="border-bottom: 1px solid #ddd;">
                    <td style="padding: 8px; font-weight: bold;">Metric</td>
                    <td style="padding: 8px; text-align: right; font-weight: bold;">Value</td>
                </tr>
                
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 8px;">💰 Spend</td>
                    <td style="padding: 8px; text-align: right;">₹${(metrics.spend || 0).toFixed(2)}</td>
                </tr>
                
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 8px;">👁️ Impressions</td>
                    <td style="padding: 8px; text-align: right;">${(metrics.impressions || 0).toLocaleString()}</td>
                </tr>
                
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 8px;">🖱️ Clicks</td>
                    <td style="padding: 8px; text-align: right;">${(metrics.clicks || 0).toLocaleString()}</td>
                </tr>
                
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 8px;">📈 CTR</td>
                    <td style="padding: 8px; text-align: right;">${(metrics.ctr || 0).toFixed(2)}%</td>
                </tr>
                
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 8px;">💵 CPC</td>
                    <td style="padding: 8px; text-align: right;">₹${(metrics.cpc || 0).toFixed(2)}</td>
                </tr>
                
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 8px;">📡 Reach</td>
                    <td style="padding: 8px; text-align: right;">${(metrics.reach || 0).toLocaleString()}</td>
                </tr>
                
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 8px;">🔄 Frequency</td>
                    <td style="padding: 8px; text-align: right;">${(metrics.frequency || 0).toFixed(2)}</td>
                </tr>
                
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 8px;">✅ Conversions</td>
                    <td style="padding: 8px; text-align: right;">${(metrics.conversions || 0).toLocaleString()}</td>
                </tr>
                
                <tr style="border-bottom: 1px solid #eee;">
                    <td style="padding: 8px;">💹 ROAS</td>
                    <td style="padding: 8px; text-align: right;">${(metrics.purchase_roas || 0).toFixed(2)}x</td>
                </tr>
            </table>
            
            <p style="color: #888; font-size: 12px; margin-top: 20px;">
                📌 Analytics saved in: <strong>${analytics_doc || 'New document'}</strong>
            </p>
        </div>
    `;

    frappe.msgprint({
        title: __('📊 Ad Set Analytics'),
        message: html,
        indicator: 'green'
    });
}

function toggle_status_fields(frm) {
    const is_enabled = frm.doc.enable_ad_set;
    if (!is_enabled) {
        frm.set_value('status', 'PAUSED');
    }
}

function toggle_budget_section_visibility(frm) {
    /**
     * Show/hide budget section based on campaign's CBO setting
     * 
     * CBO = Campaign Budget Optimization (custom_enable_adset_budget_sharing)
     * 
     * If Campaign has CBO ON (custom_enable_adset_budget_sharing=1):
     *   → Budget is managed at campaign level
     *   → Hide budget section in Ad Set form
     * 
     * If Campaign has CBO OFF (custom_enable_adset_budget_sharing=0):
     *   → Budget MUST be at ad set level
     *   → Show budget section in Ad Set form
     */
    if (!frm.doc.campaign) {
        // No campaign selected, show budget section (user will select campaign)
        frm.set_df_property('section_break_aixe', 'hidden', 0);
        frm.refresh_field('section_break_aixe');
        console.log('[AdSet JS] No campaign selected - Budget section VISIBLE');
        return;
    }

    frappe.call({
        method: 'frappe.client.get',
        args: {
            doctype: 'Marketing Campaign',
            name: frm.doc.campaign
        },
        callback: function (r) {
            if (r.message) {
                const campaign = r.message;
                const has_cbo = campaign.custom_enable_adset_budget_sharing;

                // Show budget section if CBO is disabled (budget required at ad set level)
                const should_hide = has_cbo ? 1 : 0;
                frm.set_df_property('section_break_aixe', 'hidden', should_hide);
                frm.refresh_field('section_break_aixe');

                console.log(`[AdSet JS] Campaign: ${campaign.name} | CBO: ${has_cbo} | Budget section: ${should_hide ? 'HIDDEN' : 'VISIBLE'}`);
            }
        }
    });
}

