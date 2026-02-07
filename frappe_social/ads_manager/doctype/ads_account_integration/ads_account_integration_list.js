// Copyright (c) 2026, Abhishek and contributors
// For license information, please see license.txt

frappe.listview_settings['Ads Account Integration'] = {
    add_fields: ['connection_status', 'enabled'],

    get_indicator(doc) {
        if (doc.connection_status === 'Connected') {
            return [__('Connected'), 'green', 'connection_status,=,Connected'];
        } else if (doc.connection_status === 'Expired') {
            return [__('Expired'), 'orange', 'connection_status,=,Expired'];
        } else if (doc.connection_status === 'Error') {
            return [__('Error'), 'red', 'connection_status,=,Error'];
        } else {
            return [__('Not Connected'), 'grey', 'connection_status,=,Not Connected'];
        }
    },

    onload(listview) {
        listview.page.clear_primary_action();

        listview.page.set_primary_action(__('Connect Account'), () => show_connect_dialog(), 'add');

        listview.page.add_action_item(__('Disconnect Selected'), () => {
            const selected = listview.get_checked_items();
            if (!selected.length) {
                frappe.msgprint(__('Please select at least one account'));
                return;
            }

            frappe.confirm(
                __('Disconnect {0} selected account(s)?', [selected.length]),
                () => {
                    selected.forEach(row => {
                        frappe.call({
                            method: 'frappe.client.set_value',
                            args: {
                                doctype: 'Ads Account Integration',
                                name: row.name,
                                fieldname: {
                                    connection_status: 'Not Connected',
                                    access_token: null,
                                    refresh_token: null,
                                    token_expiry: null
                                }
                            }
                        });
                    });
                    listview.refresh();
                }
            );
        });
    },

    refresh(listview) {
        listview.page.clear_primary_action();
        listview.page.set_primary_action(
            __('Connect Account'),
            () => show_connect_dialog(),
            'add'
        );
    }
};


// =======================
// OAuth Dialog
// =======================

function show_connect_dialog() {
    const d = new frappe.ui.Dialog({
        title: __('Connect New Ads Account'),
        fields: [
            {
                fieldname: 'platform',
                fieldtype: 'Select',
                label: __('Platform'),
                options: ['Facebook', 'Instagram'],
                default: 'Facebook',
                reqd: 1
            },
            {
                fieldname: 'account_name',
                fieldtype: 'Data',
                label: __('Account Name'),
                reqd: 1
            },
            {
                fieldname: 'account_description',
                fieldtype: 'Small Text',
                label: __('Description')
            },
            {
                fieldname: 'organization',
                fieldtype: 'Link',
                label: __('Organization'),
                options: 'CRM Organization'
            }
        ],
        primary_action_label: __('Connect'),
        primary_action: function (values) {
            d.hide();
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


// =======================
// OAuth Start
// =======================

function connect_platform(data) {
    frappe.call({
        method: 'frappe_social.ads_manager.api.oauth.initiate_oauth',
        args: {
            platform: data.platform,
            account_name: data.account_name,
            account_description: data.account_description || '',
            organization: data.organization || null
        },
        freeze: true,
        freeze_message: __('Redirecting to {0}...', [data.platform]),
        callback(r) {
            if (r.message && r.message.authorization_url) {
                window.location.href = r.message.authorization_url;
            } else {
                frappe.msgprint({
                    title: __('Authorization Failed'),
                    indicator: 'red',
                    message: __('Unable to start OAuth. Check Ads Setting and Meta App config.')
                });
            }
        }
    });
}
