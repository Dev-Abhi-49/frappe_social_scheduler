// Copyright (c) 2026, Frappe Social and contributors
// For license information, please see license.txt
frappe.ui.form.on('Social Post', {
    refresh: function (frm) {
        if (frm.is_new()) {
            $('.page-actions button.text-muted.btn.btn-default.icon-btn').hide();
            $('.page-actions button.btn.btn-default.icon-btn').hide();
            $('.page-actions button.btn.btn-default.ellipsis').hide();
        } else {
            $('.page-actions button.btn.btn-default.ellipsis').show();
            $('.btn-secondary[data-label="Cancel"]').remove();
            document.querySelector('.menu-btn-group').style.display = 'none';
            $('.page-actions button.text-muted.btn.btn-default.icon-btn').hide();
            $('.page-actions button.text-muted.btn.btn-default.prev-doc').show();
            $('.page-actions button.text-muted.btn.btn-default.next-doc').show();
        }

        frm.dashboard.clear_headline();
        apply_filters(frm);
        update_account_details(frm);
        update_character_count(frm);
        start_live_character_count(frm);
        frm.trigger('update_status_indicator');

        frm.dashboard.set_headline(`
            <div style="color: #e4a63cff; font-weight: 600; font-size: 15px; text-align: center;">
                ⚠️ Please note that you need to Save the Post first for you to be able to Publish or Schedule
            </div>
        `);

        if (frm.doc.status === 'Published') {
            frm.dashboard.clear_headline();
        }

        frm.get_field('character_limit').$wrapper.css({ 'margin': '0', 'padding': '0', 'width': '100%' });

        if (frm.doc.status === 'Draft') {
            if (!frm.is_dirty()) {
                frm.add_custom_button(__('Publish Now'), () => frm.trigger('publish_now'), __('Actions'));
                frm.add_custom_button(__('Schedule Post'), () => frm.trigger('schedule_post'), __('Actions'));
            }
        }

        if (frm.doc.status === 'Scheduled') {
            frm.add_custom_button(__('Publish Now'), function () { frm.trigger('publish_now'); }, __('Actions'));
            frm.add_custom_button(__('Reschedule Post'), function () { frm.trigger('reschedule_post'); }, __('Actions'));
            frm.add_custom_button(__('Cancel'), function () { frm.trigger('cancel_post'); }, __('Actions'));
        }

        if (frm.doc.status === 'Failed') {
            frm.add_custom_button(__('Retry'), function () { frm.trigger('retry_post'); }, __('Actions'))
            frm.add_custom_button(__('Reschedule Post'), function () { frm.trigger('reschedule_post'); }, __('Actions'));
        }

        if (frm.doc.status === 'Cancelled') {
            frm.add_custom_button(__('Publish Now'), function () { frm.trigger('publish_now'); }, __('Actions'));
            frm.add_custom_button(__('Reschedule Post'), function () { frm.trigger('reschedule_post'); }, __('Actions'));
        }

        if (frm.doc.status === 'Published') {
            frm.add_custom_button(__('Fetch Analytics'), function () { frm.trigger('fetch_post_analytics'); }, __('Actions'));
            frm.add_custom_button(__('View Analytics'), function () {
                frappe.set_route('List', 'Social Post Analytics', { social_post: frm.doc.name });
            }, __('Actions'));
        }

        if (frm.doc.link && !frm.doc.url_build) {
            auto_build_utm(frm);
        }

        let checked = 0;
        if (frm.doc.is_post) checked++;
        if (frm.doc.is_story) checked++;
        if (frm.doc.is_reel) checked++;
        if (checked > 1) {
            // Optionally auto-resolve (e.g., prioritize one) or alert
            frappe.msgprint('Only one option allowed. Resetting others.');
            frm.set_value('is_story', 0);
            frm.set_value('is_reel', 0);
        }
    },


    is_post(frm) {
        if (frm.doc.is_post) {
            frm.set_value('is_story', 0);
            frm.set_value('is_reel', 0);
        }
    },
    is_story(frm) {
        if (frm.doc.is_story) {
            frm.set_value('is_post', 0);
            frm.set_value('is_reel', 0);
        }
    },
    is_reel(frm) {
        if (frm.doc.is_reel) {
            frm.set_value('is_post', 0);
            frm.set_value('is_story', 0);
        }
    },

    update_status_indicator: function (frm) {
        let indicator = 'grey';
        let status = frm.doc.status;

        if (status === 'Draft') indicator = 'grey';
        else if (status === 'Scheduled') indicator = 'blue';
        else if (status === 'Publishing') indicator = 'royalblue';
        else if (status === 'Published') indicator = 'green';
        else if (status === 'Failed') indicator = 'orange';
        else if (status === 'Cancelled') indicator = 'red';

        frm.page.set_indicator(status, indicator);
    },

    after_save: function (frm) {
        if (frm.doc.status === 'Draft') {
            frappe.msgprint({
                title: __('Post Saved'),
                message: __("Post schedule has been saved. Please note that the Post will be scheduled only when you <strong>Schedule</strong> it or <strong>Publish</strong> it now."),
                indicator: 'blue',
                wide: true
            }, 4);
        }
    },

    scheduled_time: function (frm) {
        if (!frm.doc.scheduled_time) return;

        const selected = moment(frm.doc.scheduled_time);
        const now = moment();

        if (selected.isBefore(now)) {
            frappe.msgprint({
                title: __("Invalid Time"),
                message: __("You cannot schedule a post for a past time."),
                indicator: "red"
            });
            frm.set_value("scheduled_time", null);
        }
    },

    publish_now: function (frm) {
        frappe.confirm(
            __('Are you sure you want to publish post now?'),
            function () {
                frappe.call({
                    method: 'frappe_social.frappe_social.api.posts.publish_now',
                    args: { post_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Publishing...'),
                    callback: function (r) {
                        if (r.message) {
                            if (r.message.success) {
                                frappe.msgprint({
                                    message: __('Post published successfully'),
                                    indicator: 'green'
                                });
                            } else {
                                frappe.msgprint({
                                    message: __('Publishing failed: ') + (r.message.error_message || 'Check error log'),
                                    indicator: 'red'
                                });
                            }
                            frm.reload_doc();
                        }
                    }
                });
            }
        );
    },

    schedule_post: function (frm) {
        const now = moment();
        const existing = frm.doc.scheduled_time ? moment(frm.doc.scheduled_time) : null;

        // 1. If valid future time exists → confirm first
        if (existing && existing.isAfter(now)) {
            const timeStr = frappe.datetime.str_to_user(frm.doc.scheduled_time);

            frappe.confirm(
                __('Schedule this post for {0}?', [timeStr]),
                () => {
                    // Confirmed → schedule
                    frappe.call({
                        method: 'frappe_social.frappe_social.api.posts.schedule',
                        args: {
                            post_name: frm.doc.name,
                            scheduled_time: frm.doc.scheduled_time
                        },
                        freeze: true,
                        freeze_message: __('Scheduling...'),
                        callback: function (r) {
                            if (r.message?.success) {
                                frappe.msgprint({
                                    message: __('Post has been Scheduled, it is set to be posted on {0}. To cancel, use cancel option on the Post page', [timeStr]),
                                    indicator: 'blue'
                                });
                            } else {
                                frappe.msgprint({
                                    message: __('Failed to schedule: ') + (r.message?.error_message || 'Unknown error'),
                                    indicator: 'red'
                                });
                            }
                            frm.reload_doc();
                        }
                    });
                },
                () => {
                    // Cancelled confirmation → show picker
                    show_new_time_prompt();
                }
            );
        }
        // 2. No time or past time → directly show picker
        else {
            show_new_time_prompt();
        }

        function show_new_time_prompt() {
            frappe.prompt({
                label: __('Schedule Time'),
                fieldname: 'scheduled_time',
                fieldtype: 'Datetime',
                reqd: 1
                // No default → opens empty
            }, function (values) {
                const selected = moment(values.scheduled_time);

                if (selected.isBefore(now)) {
                    // Show error and RE-OPEN prompt after alert
                    frappe.show_alert({
                        message: __('Cannot schedule for a past time. Please select a future time.'),
                        indicator: 'red'
                    }, 5);  // auto-close after 5 seconds

                    // Give a tiny delay so alert doesn't overlap with new dialog
                    setTimeout(() => {
                        show_new_time_prompt();
                    }, 300);  // 300ms delay is usually enough

                    return;
                }

                // Valid time → schedule it
                frappe.call({
                    method: 'frappe_social.frappe_social.api.posts.schedule',
                    args: {
                        post_name: frm.doc.name,
                        scheduled_time: values.scheduled_time
                    },
                    freeze: true,
                    freeze_message: __('Scheduling...'),
                    callback: function (r) {
                        if (r.message?.success) {
                            const timeStr = frappe.datetime.str_to_user(values.scheduled_time);
                            frappe.msgprint({
                                message: __('Post has been Scheduled, it is set to be posted on {0}. To cancel, use cancel option on the Post page', [timeStr]),
                                indicator: 'blue'
                            });
                        } else {
                            frappe.msgprint({
                                message: __('Failed to schedule: ') + (r.message?.error_message || 'Unknown error'),
                                indicator: 'red'
                            });
                        }
                        frm.reload_doc();
                    }
                });
            }, __('Schedule Post'));
        }
    },
    reschedule_post: function (frm) {
        function show_reschedule_prompt() {
            frappe.prompt({
                label: __('Scheduled Time'),
                fieldname: 'scheduled_time',
                fieldtype: 'Datetime',
                reqd: 1,
            }, function (values) {
                const selected = moment(values.scheduled_time);
                const now = moment();

                if (selected.isBefore(now)) {
                    frappe.show_alert({
                        message: __('Cannot reschedule for a past time. Please select a future time.'),
                        indicator: 'red'
                    }, 5);

                    setTimeout(() => {
                        show_reschedule_prompt();  // ← re-open prompt
                    }, 300);

                    return;
                }

                // Valid → proceed
                frappe.call({
                    method: 'frappe_social.frappe_social.api.posts.schedule',
                    args: {
                        post_name: frm.doc.name,
                        scheduled_time: values.scheduled_time
                    },
                    freeze: true,
                    freeze_message: __('Rescheduling...'),
                    callback: function (r) {
                        if (r.message?.success) {
                            const time_str = frappe.datetime.str_to_user(values.scheduled_time);
                            frappe.msgprint({
                                message: __('Post rescheduled for ') + time_str,
                                indicator: 'blue'
                            });
                        } else {
                            frappe.msgprint({
                                message: __('Failed to reschedule: ') + (r.message?.error_message || 'Unknown error'),
                                indicator: 'red'
                            });
                        }
                        frm.reload_doc();
                    }
                });
            }, __('Reschedule Post'));
        }

        show_reschedule_prompt();
    },

    cancel_post: function (frm) {
        frappe.confirm(
            __('Are you sure you want to cancel this scheduled post?'),
            function () {
                frappe.call({
                    method: 'frappe_social.frappe_social.api.posts.cancel',
                    args: { post_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Cancelling...'),
                    callback: function (r) {
                        if (r.message && r.message.success) {
                            // Exact message you requested
                            frappe.msgprint({
                                message: __("Post schedule has been cancelled, however you can come back and publish it later."),
                                indicator: 'blue'
                            });

                            frm.reload_doc();
                        } else {
                            frappe.msgprint({
                                message: __('Failed to cancel post') + (r.message?.error_message || ''),
                                indicator: 'red'
                            });
                        }
                    }
                });
            }
        );
    },

    retry_post: function (frm) {
        frappe.confirm(
            __('Retry publishing this failed post?'),
            function () {
                frappe.call({
                    method: 'frappe_social.frappe_social.api.posts.publish_now',
                    args: { post_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Retrying...'),
                    callback: function (r) {
                        if (r.message && r.message.success) {
                            frappe.show_alert({
                                message: __('Post retry initiated'),
                                indicator: 'green'
                            });
                            frm.reload_doc();
                        } else {
                            frappe.msgprint({
                                message: __('Retry failed: ') + (r.message?.error_message || 'Check error log'),
                                indicator: 'red'
                            });
                        }
                    }
                });
            }
        );
    },

    organization: function (frm) {
        frm.set_value('platform', '');
        frm.set_value('account', '');
        apply_filters(frm);
        update_account_details(frm);
    },

    platform: function (frm) {
        frm.set_value('account', '');
        apply_filters(frm);
        update_account_details(frm);
        update_character_count(frm);
        auto_build_utm(frm);
    },

    link: function (frm) {
        auto_build_utm(frm)
    },

    account: function (frm) {
        update_account_details(frm);
    },

    content: function (frm) {
        update_character_count(frm);
    },


    fetch_post_analytics: function (frm) {
        frappe.call({
            method: 'frappe_social.frappe_social.api.analytics.fetch_post_analytics_now',
            args: { post_name: frm.doc.name },
            freeze: true,
            freeze_message: __('Fetching analytics...'),
            callback: function (r) {
                if (r.message) {
                    if (r.message.success) {
                        frappe.show_alert({
                            message: __('Analytics fetched for ') + Object.keys(r.message.results || {}).join(', '),
                            indicator: 'green'
                        });
                        // Optionally navigate to analytics
                        frappe.set_route('List', 'Social Post Analytics', {
                            social_post: frm.doc.name
                        });
                    } else {
                        frappe.show_alert({
                            message: __('Failed to fetch analytics'),
                            indicator: 'red'
                        });
                    }
                }
            }
        });
    },

});

let live_interval = null;

function start_live_character_count(frm) {
    // Clear any existing interval
    if (live_interval) clearInterval(live_interval);

    // Check every 100ms if content changed
    live_interval = setInterval(() => {
        if (frm.doc.content !== frm.last_content_value) {
            frm.last_content_value = frm.doc.content;
            update_character_count(frm);
        }
    }, 100);

    // Store initial value
    frm.last_content_value = frm.doc.content || '';
}

// Stop interval when leaving form (good practice)
$(document).on('form-unload', function (event, frm) {
    if (frm.doctype === 'Social Post' && live_interval) {
        clearInterval(live_interval);
    }
});

function update_character_count(frm) {
    let content = frm.doc.content || '';
    // Strip HTML for plain text count
    let div = document.createElement('div');
    div.innerHTML = content;
    let text = div.textContent || div.innerText || '';
    let count = text.length;

    const limits = {
        'Twitter': 280,
        'LinkedIn': 3000,
        'Facebook': 63206,
        'Instagram': 2200,
        'YouTube': 5000
    };

    let platform = frm.doc.platform || '';
    let limit = limits[platform] || 0;
    let isExceeded = count > limit;

    // Function to apply the correct colors based on current theme
    function applyColors() {
        const isDark = document.documentElement.getAttribute('data-theme').includes('dark');

        let textColor;
        if (isExceeded) {
            textColor = isDark ? '#ff6b6b' : '#c62828';        // Bright red / Dark red
        } else {
            textColor = isDark ? '#ffffff' : '#000000';        // Light gray / Dark gray
        }

        const message = isExceeded ?
            `Exceeded limit: ${platform} (${count}/${limit})` :
            `Character limit: ${platform} (${count}/${limit})`;

        const html_content = `
            <div style="
                display: flex;
                justify-content: flex-end;
                align-items: center;
            ">
                <div style="
                    display: flex;
                    align-items: center;
                    color: ${textColor};
                    font-weight: 400;
                    font-size: 12px;
                ">
                    <span>${message}</span>
                </div>
            </div>
        `;

        frm.get_field('character_limit').$wrapper.html(html_content);
    }

    // Initial apply
    applyColors();
    frm.page.wrapper.on('theme-change', applyColors);

    // Optional: Also listen to attribute change as fallback (covers most cases)
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.type === 'attributes' && mutation.attributeName === 'data-theme') {
                applyColors();
            }
        });
    });

    observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme']
    });
}

function apply_filters(frm) {
    filter_platform_field(frm);
    filter_account_field(frm);
}

function filter_platform_field(frm) {
    const organization = frm.doc.organization;

    frm.set_df_property('platform', 'options', ['']);

    if (!organization) {
        update_account_details(frm);
        return;
    }

    frappe.call({
        method: "frappe_social.frappe_social.doctype.social_post.social_post.get_platforms_for_organization",
        args: { organization: organization },
        callback: function (r) {
            let platforms = r.message || [];
            let options = [''];
            if (platforms.length > 0) {
                options = options.concat(platforms);
            }
            frm.set_df_property('platform', 'options', options);

            if (frm.doc.platform && !platforms.includes(frm.doc.platform)) {
                frm.set_value('platform', '');
            }

            update_account_details(frm);
        },
        error: function () {
            frappe.msgprint("Failed to load platforms.");
            update_account_details(frm);
        }
    });
}

function filter_account_field(frm) {
    const organization = frm.doc.organization;
    const platform = frm.doc.platform;

    if (!organization || !platform) {
        frm.set_query('account', () => ({ filters: { name: ["in", []] } }));
        frm.set_value('account', '');
        update_account_details(frm);
        return;
    }

    frm.set_query('account', () => ({
        filters: {
            organization: organization,
            platform: platform,
            enabled: 1,
            connection_status: 'Connected'
        }
    }));

    update_account_details(frm);
}

function update_account_details(frm) {
    const org = frm.doc.organization || "Not selected";
    const platform = frm.doc.platform || "Not selected";
    const account = frm.doc.account;
    const html_field = frm.get_field('html'); // CHANGE TO YOUR ACTUAL HTML FIELD NAME

    if (!html_field) return;

    async function renderHTML() {
        const themeAttr = document.documentElement.getAttribute('data-theme') || '';
        const isDark = themeAttr.includes('dark');

        const colors = {
            containerBg: isDark ? '#1b1a1aff' : '#ffffff',
            containerBorder: isDark ? '#4a5568' : '#e2e8f0',
            containerShadow: isDark ? '0 4px 12px rgba(0,0,0,0.4)' : '0 4px 12px rgba(0,0,0,0.1)',
            // textPrimary: isDark ? '#e2e8f0' : '#4a5568',
            textSecondary: isDark ? '#ffffff' : '#000000',
            textHeading: isDark ? '#ffffff' : '#09223a',
            platformColor: isDark ? '#abcde6' : '#0c466d',
            placeholderText: isDark ? '#a0aec0' : '#7f8c8d',
            placeholderBorder: isDark ? '#4a5568' : '#cbd5e1',
            errorColor: isDark ? '#d48d8dff' : '#e74c3c',
            fallbackText: isDark ? '#e2e8f0' : '#718096'
        };

        let html_content = '';

        if (!account) {
            html_content = `
                <div style="padding: 10px; border: 1px dashed ${colors.placeholderBorder}; border-radius: 8px; 
                            color: ${colors.placeholderText}; font-style: italic; text-align: center; font-size: 14px;">
                    Select an Organization → Platform → Account to see details here
                </div>`;
        } else {
            try {
                // CORRECT client-side way to fetch a single doc
                const response = await frappe.db.get_doc('Social Integration', account);
                const integration = response; // In newer versions it's direct, in older it's response.message

                const profile_image = integration.profile_image || '';
                const account_name = integration.account_name || '—';
                const account_description = integration.account_description || '—';

                let img_html = '';
                if (profile_image) {
                    img_html = `<img src="${profile_image}" alt="Profile" style="width: 80px; height: 80px; border-radius: 50%; object-fit: cover; display: block; ">`;
                } else {
                    img_html = `<div style="width: 80px; height: 80px; border-radius: 50%; background: linear-gradient(135deg, ${colors.platformColor}, ${isDark ? '#4299e1' : '#3182ce'}); 
                                color: ${colors.fallbackText}; display: flex; align-items: center; justify-content: center; 
                                font-size: 28px; font-weight: bold; margin: 0 auto 15px;">
                        ${account_name.charAt(0).toUpperCase() || '?'}
                    </div>`;
                }

                html_content = `
                    <div>
                        <header style="color: red; text-align: center;">
                            <p><strong>Please look at these details to ensure that you have selected the right account</strong></p>
                        </header>

                        <div style="
                            padding: 20px;
                            border-radius: 12px;
                            background-color: ${colors.containerBg};
                            box-shadow: ${colors.containerShadow};
                            border: 1px solid ${colors.containerBorder};
                            margin: 10px 0;
                        ">
                            <div style="display: flex; align-items: flex-start; gap: 40px; flex-wrap: wrap;">
                                <!-- Profile Image -->
                                ${img_html}

                                <!-- Three Columns Layout -->
                                <div style="
                                    display: grid;
                                    grid-template-columns: repeat(3, 1fr);
                                    gap: 20px 50px;
                                    flex: 1;
                                    font-size: 14px;
                                    line-height: 1.8;
                                    min-width: 600px;
                                ">
                                    <!-- Column 1: Organization & Platform -->
                                    <div style="margin-top: 10px;">
                                        <div style="margin-bottom: 12px;">
                                            <strong>Organization :</strong>
                                            <span style="color: ${colors.textSecondary}; margin-left: 8px;">${org}</span>
                                        </div>
                                        <div>
                                            <strong>Platform :</strong>
                                            <span style="color: ${colors.platformColor}; font-weight: 600; margin-left: 8px;">${platform}</span>
                                        </div>
                                    </div>

                                    <!-- Column 2: Account ID & Account Name -->
                                    <div style="margin-top: 10px;">
                                        <div style="margin-bottom: 12px;">
                                            <strong>Account ID :</strong>
                                            <span style="color: ${colors.textSecondary}; margin-left: 8px;">${account}</span>
                                        </div>
                                        <div>
                                            <strong>Account Name :</strong>
                                            <span style="font-weight: 600; color: ${colors.textHeading}; margin-left: 8px;">${account_name}</span>
                                        </div>
                                    </div>

                                    <!-- Column 3: Description - properly aligned and wrapped -->
                                    <div style="display: flex; align-items: flex-start; margin-top: 10px;">
                                        <strong style="flex-shrink: 0;">Description :</strong>
                                        <span style="
                                            color: ${colors.textSecondary};
                                            margin-left: 8px;
                                            word-break: break-word;
                                            overflow-wrap: anywhere;
                                            line-height: 1.6;
                                        ">
                                            ${account_description || '—'}
                                        </span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
            } catch (err) {
                html_content = `
                    <div style="padding: 20px; border-radius: 8px; color: ${colors.errorColor}; text-align: center; font-size: 14px;">
                        Unable to load account details.<br><small>${err.message || 'Permission denied or document not found'}</small>
                    </div>`;
            }
        }

        // Safely update HTML
        html_field.html(html_content);
    }

    // Initial render
    renderHTML();

    // Re-render when relevant fields change
    ['organization', 'platform', 'account'].forEach(field => {
        frm.fields_dict[field]?.input?.addEventListener('change', renderHTML);
    });

    // Theme change handling
    frm.page.wrapper.on('theme-change', renderHTML);

    const observer = new MutationObserver(() => renderHTML());
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
}

frappe.ui.form.on('Social Post Media', {
    file: function (frm, cdt, cdn) {
        let row = frappe.get_doc(cdt, cdn);


        if (!frm.doc.file) return;

        frappe.db.get_value(
            'File',
            { file_url: frm.doc.file },
            ['file_size', 'file_type'],
            (r) => {
                if (r) {
                    frm.set_value('file_size', r.file_size);
                    frm.set_value('file_type', r.file_type);
                }
            }
        );
    }
});

let utm_build_timeout = null;

function auto_build_utm(frm) {
    // Clear any existing timeout
    if (utm_build_timeout) {
        clearTimeout(utm_build_timeout);
    }

    if (!frm.doc.link) {
        return;
    }

    utm_build_timeout = setTimeout(() => {
        auto_build_utm_url(frm);
    }, 1000);
}

function auto_build_utm_url(frm) {
    // Only auto-build if we have the necessary info
    if (!frm.doc.link) {
        return;
    }

    // Validate and fix URL format
    let link = frm.doc.link.trim();
    let url;

    try {
        // Try to parse the URL
        url = new URL(link);
    } catch (e) {
        // If it fails, try adding https://
        if (!link.startsWith('http://') && !link.startsWith('https://')) {
            try {
                // Add https:// for url_build, but DON'T update the link field
                url = new URL('https://' + link);

            } catch (e2) {

                return;
            }
        } else {
            return;
        }

        // Auto-fill UTM parameters
        let utm_source = '';
        let utm_medium = 'social';
        let utm_campaign = '';
        let utm_postname = '';

        // Get utm_source from platform
        if (frm.doc.platform) {
            utm_source = frm.doc.platform.toLowerCase();
        }

        if (frm.doc.post_name) {
            utm_postname = frm.doc.post_name.toLowerCase();
        }

        // Get utm_campaign from campaign field
        if (frm.doc.campagin) {
            frappe.db.get_value('Marketing Campaign', frm.doc.campagin, 'name', (r) => {
                if (r && r.name) {
                    utm_campaign = r.name.toLowerCase().replace(/\s+/g, '_');
                    build_and_set_url(frm, url, utm_source, utm_medium, utm_campaign, utm_postname);
                } else {
                    build_and_set_url(frm, url, utm_source, utm_medium, utm_campaign, utm_postname);
                }
            });
        } else {
            build_and_set_url(frm, url, utm_source, utm_medium, utm_campaign, utm_postname);
        }
    }

    // Build and set the URL
    function build_and_set_url(frm, url, utm_source, utm_medium, utm_campaign, utm_postname) {
        // Only build if we have at least source and medium
        if (!utm_source || !utm_campaign) {
            let missing = [];
            if (!utm_source) missing.push('Platform');
            if (!utm_campaign) missing.push('Campaign');

            frappe.show_alert({
                message: __('⚠️ Cannot build UTM URL. Missing: ') + missing.join(', '),
                indicator: 'orange'
            }, 5);
            return;
        }

        // Add UTM parameters
        if (utm_source) url.searchParams.set('utm_wsource', utm_source);
        if (utm_medium) url.searchParams.set('utm_wmedium', utm_medium);
        if (utm_campaign) url.searchParams.set('utm_wcampaign', utm_campaign);
        if (utm_postname) url.searchParams.set('utm_wpostname', utm_postname);

        const built_url = url.toString();

        // Only update if it's different
        if (frm.doc.url_build !== built_url) {
            frm.set_value('url_build', built_url);

            // Show detailed notification
            let params_text = `${utm_source}/${utm_medium}`;
            if (utm_campaign) params_text += `/${utm_campaign}`;
            if (utm_postname) params_text += `/${utm_postname}`;

        }
    }
}