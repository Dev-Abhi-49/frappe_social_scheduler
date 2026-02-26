// Copyright (c) 2026, Abhishek and contributors
// For license information, please see license.txt

(function () {
    const hash = window.location.hash;
    let oauth_success = null;

    if (hash) {
        const hashMatch = hash.match(/oauth_success=([^&]+)/);
        if (hashMatch) {
            oauth_success = decodeURIComponent(hashMatch[1]);
        }
    }

    // Check if we're in a popup window
    const isInPopup = window.opener !== null && window.opener !== undefined;

    // If this is an OAuth success callback in a popup
    if (oauth_success && isInPopup) {

        // Check if parent is still open
        if (window.opener.closed) {
            console.error('Parent window is closed');
            alert('Parent window was closed. Please reopen and try again.');
            window.close();
            return;
        }

        try {
            window.opener.postMessage({
                type: 'oauth_complete',
                integration: oauth_success
            }, window.location.origin);

        } catch (e) {
            console.error('✗ Failed to send message to parent:', e);
        }

        setTimeout(function () {
            window.close();

            // Fallback if window.close() fails
            setTimeout(function () {
                console.log('Checking if window closed...');
                try {
                    // Try to detect if we're still open
                    document.title = 'Authorization Complete - Close This Window';
                    alert('Authorization Complete! You can close this window now.');
                } catch (e) {
                    console.log('Window closed successfully');
                }
            }, 300);
        }, 800);
    } else {
        if (oauth_success && !isInPopup) {
            frappe.show_alert({
                message: __('Account connected successfully'),
                indicator: 'green'
            }, 5);

            // Clean the hash
            if (window.history && window.history.replaceState) {
                window.history.replaceState(null, null, window.location.pathname);
            }
        }
    }
})();

frappe.ui.form.on('Ads Account Integration', {
    refresh: function (frm) {
        // Block manual creation - redirect to list
        if (frm.is_new()) {
            frappe.set_route('List', 'Ads Account Integration');
            return;
        }

        // Add Connect button for disconnected integrations
        if (frm.doc.connection_status !== 'Connected') {
            frm.add_custom_button(__('Connect Account'), function () {
                frm.trigger('connect_account');
            }, __('Actions'));
        }

        // Add buttons for connected integrations
        if (frm.doc.connection_status === 'Connected') {
            frm.add_custom_button(__('Disconnect'), function () {
                frm.trigger('disconnect_account');
            }, __('Actions'));

            frm.add_custom_button(__('Test Connection'), function () {
                frm.trigger('test_connection');
            }, __('Actions'));

            frm.add_custom_button(__('Fetch Analytics'), function () {
                frm.trigger('fetch_analytics');
            }, __('Actions'));
        }

        if (frm.doc.authorized_user_name) {
            frm.set_intro(__('Authorized via: {0}', [frm.doc.authorized_user_name]), 'blue');
        }

        frm.trigger('update_status_indicator');
    },

    connect_account: function (frm) {
        // Call OAuth initiation
        //     frappe.call({
        //         method: 'frappe_social.ads_manager.api.oauth.initiate_oauth',
        //         args: {
        //             platform: frm.doc.platform,
        //             integration: frm.doc.name
        //         },
        //         callback: function (r) {
        //             if (r.message && r.message.authorization_url) {
        //                 const popup = window.open(
        //                     r.message.authorization_url,
        //                     'oauth_popup',
        //                     'width=600,height=700,scrollbars=yes'
        //                 );

        //                 frappe.show_alert({
        //                     message: __('Complete authorization in the popup window'),
        //                     indicator: 'blue'
        //                 });

        //                 const pollTimer = setInterval(function () {
        //                     if (popup.closed) {
        //                         clearInterval(pollTimer);
        //                         frm.reload_doc();
        //                     }
        //                 }, 1000);
        //             }
        //         }
        //     });
        // },

        let popup = null;
        let checkClosed = null;

        const messageHandler = function (event) {

            // Verify origin for security
            if (event.origin !== window.location.origin) {
                console.warn('Message from wrong origin:', event.origin);
                return;
            }

            if (event.data && event.data.type === 'oauth_complete') {
                // Cleanup
                if (checkClosed) {
                    clearInterval(checkClosed);
                }

                // Force close popup if still open
                if (popup && !popup.closed) {
                    popup.close();
                }

                window.removeEventListener('message', messageHandler);

                frappe.show_alert({
                    message: __('Account connected successfully'),
                    indicator: 'green'
                }, 5);

                frm.reload_doc();
            }
        };

        window.addEventListener('message', messageHandler);
        // console.log('Message listener added');

        // Monitor popup closure
        checkClosed = setInterval(function () {
            if (popup && popup.closed) {
                console.log('Popup closed by user');
                clearInterval(checkClosed);
                window.removeEventListener('message', messageHandler);

                frappe.show_alert({
                    message: __('Authorization window closed'),
                    indicator: 'orange'
                });
            }
        }, 500);

        frappe.call({
            method: 'frappe_social.ads_manager.api.oauth.initiate_oauth',
            args: {
                platform: frm.doc.platform,
                integration: frm.doc.name,
                account_name: frm.doc.account_name
            },
            callback: function (r) {
                if (r.message && r.message.authorization_url) {
                    const width = 600;
                    const height = 700;
                    const left = (screen.width - width) / 2;
                    const top = (screen.height - height) / 2;

                    // console.log('Opening OAuth popup...');
                    popup = window.open(
                        r.message.authorization_url,
                        'oauth_popup',
                        `width=${width},height=${height},left=${left},top=${top}`
                    );

                    if (!popup) {
                        frappe.msgprint(__('Please allow popups for this site'));
                        clearInterval(checkClosed);
                        window.removeEventListener('message', messageHandler);
                        return;
                    }

                    // console.log('Popup opened successfully');

                    frappe.show_alert({
                        message: __('Complete authorization in the popup window'),
                        indicator: 'blue'
                    });
                }
            }
        });
    },

    disconnect_account: function (frm) {
        frappe.confirm(
            __('Are you sure you want to disconnect this account?'),
            function () {
                frappe.call({
                    method: 'frappe_social.ads_manager.api.oauth.disconnect',
                    args: { integration: frm.doc.name },
                    callback: function (r) {
                        if (r.message && r.message.success) {
                            frappe.show_alert({
                                message: __('Account disconnected successfully'),
                                indicator: 'green'
                            });
                            frm.reload_doc();
                        }
                    }
                });
            }
        );
    },

    test_connection: function (frm) {
        frappe.call({
            method: 'frappe_social.ads_manager.api.oauth.test_connection',
            args: { integration: frm.doc.name },
            callback: function (r) {
                if (r.message) {
                    if (r.message.valid) {
                        frappe.show_alert({
                            message: __('Connection is valid'),
                            indicator: 'green'
                        });
                    } else {
                        frappe.show_alert({
                            message: __('Connection failed: ') + r.message.reason,
                            indicator: 'red'
                        });
                    }
                    frm.reload_doc();
                }
            }
        });
    },

    fetch_analytics: function (frm) {
        frappe.call({
            method: 'frappe_social.ads_manager.api.analytics.fetch_analytics',
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
                        frappe.show_alert({
                            message: __('Failed to fetch analytics: ') + (r.message.error_message || 'Unknown error'),
                            indicator: 'red'
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

    update_status_indicator: function (frm) {
        let indicator = 'grey';
        let status = frm.doc.connection_status;

        if (status === 'Connected') indicator = 'green';
        else if (status === 'Expired') indicator = 'orange';
        else if (status === 'Error') indicator = 'red';

        frm.page.set_indicator(status, indicator);
    }
});

/**
 * Show analytics summary dialog with key metrics
 */
function show_analytics_summary(metrics, analytics_doc) {
    let html = `
        <div style="padding: 20px;">
            <h5 style="margin-bottom: 20px; color: #333;">📊 Campaign Analytics Summary (Last 7 Days)</h5>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px;">
    `;

    const summary_metrics = [
        { label: 'Total Spend', value: metrics.spend, format: 'currency', icon: '💰' },
        { label: 'Impressions', value: metrics.impressions, format: 'number', icon: '👁️' },
        { label: 'Clicks', value: metrics.clicks, format: 'number', icon: '🖱️' },
        { label: 'CTR', value: metrics.ctr, format: 'percent', icon: '📈' },
        { label: 'CPC', value: metrics.cpc, format: 'currency', icon: '💵' },
        { label: 'Reach', value: metrics.reach, format: 'number', icon: '📢' },
        { label: 'Conversions', value: metrics.conversions, format: 'number', icon: '✅' },
        { label: 'Conv. Rate', value: metrics.conversion_rate, format: 'percent', icon: '⭐' },
        { label: 'ROAS', value: metrics.purchase_roas, format: 'decimal', icon: '💹' },
        { label: 'Active Campaigns', value: metrics.active_campaigns, format: 'number', icon: '📋' },
    ];

    summary_metrics.forEach(metric => {
        let formatted_value = format_metric_value(metric.value, metric.format);
        html += `
            <div style="
                background: white;
                padding: 12px;
                border-radius: 6px;
                border-left: 3px solid #4169e1;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            ">
                <div style="font-size: 18px; margin-bottom: 5px;">${metric.icon}</div>
                <div style="font-size: 11px; color: #666; margin-bottom: 3px;">${metric.label}</div>
                <div style="font-size: 16px; font-weight: bold; color: #2d5016;">${formatted_value}</div>
            </div>
        `;
    });

    html += `
            </div>
        </div>
    `;

    let dialog = new frappe.ui.Dialog({
        title: 'Analytics Summary',
        fields: [],
        primary_action_label: 'View Full Analytics',
        primary_action() {
            dialog.hide();
            if (analytics_doc) {
                frappe.set_route('Form', 'Ads Analytics', analytics_doc);
            }
        },
        secondary_action_label: 'Close',
        secondary_action() {
            dialog.hide();
        }
    });

    dialog.$wrapper.find('.modal-body').html(html);
    dialog.show();
}

/**
 * Format metric values based on type
 */
function format_metric_value(value, format_type) {
    if (!value) return '0';

    switch (format_type) {
        case 'currency':
            return '₹' + parseFloat(value).toFixed(2);
        case 'percent':
            return parseFloat(value).toFixed(2) + '%';
        case 'decimal':
            return parseFloat(value).toFixed(2);
        case 'number':
        default:
            let num = parseInt(value);
            if (num >= 1000000) {
                return (num / 1000000).toFixed(1) + 'M';
            } else if (num >= 1000) {
                return (num / 1000).toFixed(1) + 'K';
            }
            return num.toString();
    }
}