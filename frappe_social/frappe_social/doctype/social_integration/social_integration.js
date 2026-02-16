// Copyright (c) 2026, Frappe Social and contributors
// For license information, please see license.txt

// OAuth Popup Callback Handler - Must run IMMEDIATELY on page load
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
