// List view customization for Social Integration
frappe.listview_settings['Social Integration'] = {
    add_fields: ['connection_status',],

    get_indicator: function (doc) {
        if (doc.connection_status === 'Connected') {
            return [__("Connected"), "green", "connection_status,=,Connected"];
        } else if (doc.connection_status === 'Expired') {
            return [__("Expired"), "orange", "connection_status,=,Expired"];
        } else if (doc.connection_status === 'Error') {
            return [__("Error"), "red", "connection_status,=,Error"];
        } else {
            return [__("Not Connected"), "grey", "connection_status,=,Not Connected"];
        }
    },

    onload: function (listview) {
        // Handle successful OAuth from "Connect Account"
        const urlParams = new URLSearchParams(window.location.search);
        const oauthSuccess = urlParams.get('oauth_success');

        if (oauthSuccess) {
            frappe.show_alert({
                message: __('Account connected successfully'),
                indicator: 'green'
            }, 5);

            listview.refresh();

            // Clean URL
            window.history.replaceState({}, document.title, '/app/social-integration');
        }

        // Remove default + Add button
        listview.page.clear_primary_action();

        // Add our Connect button
        listview.page.set_primary_action(__('Connect Account'), () => show_connect_dialog(), 'add');

        // Bulk disconnect
        listview.page.add_action_item(__('Disconnect Selected'), function () {
            const selected = listview.get_checked_items();
            if (selected.length === 0) {
                frappe.msgprint(__('Please select accounts to disconnect'));
                return;
            }
            frappe.confirm(
                __('Disconnect {0} account(s)?', [selected.length]),
                function () {
                    selected.forEach(function (doc) {
                        frappe.call({
                            method: 'frappe_social.frappe_social.api.oauth.disconnect',
                            args: { integration: doc.name },
                            async: false
                        });
                    });
                    listview.refresh();
                }
            );
        });
    },

    refresh(listview) {
        listview.page.clear_primary_action();
        listview.page.set_primary_action(__('Connect Account'), () => show_connect_dialog(), 'add');
    }
};
function show_connect_dialog() {
    let d = new frappe.ui.Dialog({
        title: __('Account Integration'),
        fields: [
            {
                fieldname: 'account_name',
                fieldtype: 'Data',
                label: __('Account Name'),
                reqd: 1,
                placeholder: __('Enter Account Name')
            },
            {
                fieldname: 'account_description',
                fieldtype: 'Small Text',
                label: __('Account Description'),
                placeholder: __('Enter Account Description (optional)')
            },
            {
                fieldname: 'platform',
                fieldtype: 'Select',
                label: __('Platform'),
                options: 'Facebook\nInstagram\nInstagramStandalone\nTwitter\nLinkedIn\nYouTube',
                reqd: 1,
                placeholder: __('Select Platform')
            },
            {
                fieldname: 'organization',
                fieldtype: 'Link',
                label: __('Organization'),
                options: 'CRM Organization',
                placeholder: __('Select Organization')
            },
            {
                fieldname: 'info_section',
                fieldtype: 'Section Break'
            },
            {
                fieldname: "note",
                fieldtype: "HTML",
                options: `
                    <div class="alert alert-info" style="margin-bottom: 0;">
                        <p><strong>💡 Tip:</strong> Give your account a specific name (e.g., "Facebook - Bangalore Region") so it's easy to identify. Use the description to guide your team on when to select this account (e.g., "For all posts related to Mysore branch" or "Use for academia-related content only").</p>

                        <details style="margin: 10px 0;">
                            <summary style="cursor: pointer; color: #0d6efd; font-weight: 600;">
                                <strong>Learn more</strong>
                            </summary>

                            <div style="margin-top: 12px; padding-left: 10px; border-left: 3px solid #0d6efd;">
                                <p><strong>Naming your account:</strong> Choose a clear, descriptive name that helps your team quickly identify the account's purpose or target audience.</p>
                                <p><strong>Examples:</strong></p>
                                <ul>
                                    <li>Facebook - Bangalore Region</li>
                                    <li>Instagram - Corporate Updates</li>
                                </ul>

                                <p><strong>Adding a description:</strong> Provide instructions to help your team decide when to use this account for posting.</p>
                                <p><strong>Examples:</strong></p>
                                <ul>
                                    <li>"Use for all posts related to Mysore branch events and announcements"</li>
                                    <li>"Dedicated to academic content, research updates, and university partnerships"</li>
                                    <li>"For customer testimonials and product reviews only"</li>
                                </ul>
                            </div>
                        </details>

                        <p><strong>Before connecting:</strong></p>
                        <ul style="margin-bottom: 0; padding-left: 20px;">
                            <li><strong>Facebook/Instagram:</strong> You need a Facebook Page</li>
                            <li><strong>Instagram:</strong> Must be a Business or Creator account and should be connected to a Facebook Page</li>
                            <li><strong>Twitter:</strong> You need a Twitter account </li>
                            <li><strong>LinkedIn:</strong> Company Page required</li>
                            <li><strong>YouTube:</strong> YouTube channel required</li>
                        </ul>
                    </div>
                `
            }
        ],
        size: 'large',
        primary_action_label: __('Connect'),
        primary_action: function (values) {
            d.hide();

            // ← Correct: pass all values to connect_platform
            connect_platform({
                platform: values.platform,
                account_name: values.account_name,
                account_description: values.account_description || '',
                organization: values.organization || null
            });
        }
    });
    d.show();
}

function connect_platform(data) {
    frappe.call({
        method: 'frappe_social.frappe_social.api.oauth.initiate_oauth',
        args: {
            platform: data.platform,
            account_name: data.account_name,
            account_description: data.account_description,
            organization: data.organization
        },
        freeze: true,
        freeze_message: __('Redirecting to {0}...', [data.platform]),
        callback: function (r) {
            if (r.message && r.message.authorization_url) {
                window.location.href = r.message.authorization_url;
            } else {
                frappe.msgprint(__('Failed to initiate authorization. Check Social Settings.'));
            }
        }
    });
}