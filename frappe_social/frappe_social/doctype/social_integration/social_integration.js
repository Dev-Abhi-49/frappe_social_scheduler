// Copyright (c) 2026, Frappe Social and contributors
// For license information, please see license.txt

frappe.ui.form.on('Social Integration', {
    refresh: function (frm) {
        // Block manual creation - redirect to list
        if (frm.is_new()) {
            frappe.set_route('List', 'Social Integration');
            return;
        }

        // Add Connect button for disconnected integrations
        if (frm.doc.connection_status !== 'Connected') {
            frm.add_custom_button(__('Re-Connect'), function () {
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

        // Show authorized user info
        if (frm.doc.authorized_user_name) {
            frm.set_intro(__('Authorized via: {0}', [frm.doc.authorized_user_name]), 'blue');
        }

        // Show connection status indicator
        frm.trigger('update_status_indicator');
    },

    connect_account: function (frm) {
        let popup = null;
        let checkInterval = null;
        
        const messageHandler = function(event) {
            if (event.origin !== window.location.origin) return;

            if (event.data && event.data.type === 'oauth_complete') {
                console.log('OAuth complete:', event.data);

                if (checkInterval) {
                    clearInterval(checkInterval);
                }

                if (popup && !popup.closed) {
                    popup.close();
                }

                frappe.show_alert({
                    message: __('Account reconnected successfully'),
                    indicator: 'green'
                }, 5);

                setTimeout(() => frm.reload_doc(), 500);
                window.removeEventListener('message', messageHandler);
            }
        };

        window.addEventListener('message', messageHandler);

        frappe.call({
            method: 'frappe_social.frappe_social.api.oauth.initiate_oauth',
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

                    popup = window.open(
                        r.message.authorization_url,
                        'oauth_popup',
                        `width=${width},height=${height},left=${left},top=${top}`
                    );
                
                    if (!popup) {
                        frappe.msgprint(__('Please allow popups'));
                        window.removeEventListener('message', messageHandler);
                        return;
                    }

                    // Poll popup location
                    checkInterval = setInterval(function() {
                        if (!popup || popup.closed) {
                            clearInterval(checkInterval);
                            window.removeEventListener('message', messageHandler);
                            return;
                        }

                        try {
                            // Check if popup reached success URL
                            const popupUrl = popup.location.href;
                            if (popupUrl.includes('/app/social-integration?oauth_success=')) {
                                clearInterval(checkInterval);

                                // Extract integration name from URL
                                const urlParams = new URLSearchParams(popup.location.search);
                                const integration = urlParams.get('oauth_success');

                                // Close popup
                                popup.close();

                                // Show success message
                                frappe.show_alert({
                                    message: __('Account reconnected successfully'),
                                    indicator: 'green'
                                }, 5);

                                // Reload form
                                setTimeout(() => frm.reload_doc(), 500);
                                window.removeEventListener('message', messageHandler);
                            }
                        } catch (e) {
                            // Cross-origin error - popup is still on OAuth provider
                            // This is expected, just continue polling
                        }
                    }, 500);

                    frappe.show_alert({
                        message: __('Complete authorization in the popup'),
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
                    method: 'frappe_social.frappe_social.api.oauth.disconnect',
                    args: { integration: frm.doc.name },
                    callback: function (r) {
                        if (r.message && r.message.success) {
                            frappe.show_alert({
                                message: __('Account disconnected'),
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
            method: 'frappe_social.frappe_social.api.oauth.test_connection',
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
            method: 'frappe_social.frappe_social.api.analytics.fetch_analytics',
            args: { integration: frm.doc.name },
            freeze: true,
            freeze_message: __('Fetching analytics...'),
            callback: function (r) {
                if (r.message) {
                    if (r.message.success) {
                        frappe.show_alert({
                            message: __('Analytics fetched successfully'),
                            indicator: 'green'
                        });
                        if (r.message.analytics_doc) {
                            frappe.set_route('Form', 'Social Analytics', r.message.analytics_doc);
                        }
                    } else {
                        frappe.show_alert({
                            message: __('Failed to fetch analytics: ') + (r.message.error_message || 'Unknown error'),
                            indicator: 'red'
                        });
                    }
                }
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
