// ad_creative.js
// Copyright (c) 2026, Abhishek and contributors

frappe.ui.form.on('Ad Creative', {
    refresh(frm) {
        // Show creative ID status
        if (frm.doc.creative_id) {
            frm.set_df_property('creative_id', 'description',
                `✓ Creative created on Meta: ${frm.doc.creative_id}`);
        }

        if (frm.doc.ad_account) {
            load_facebook_pages(frm);
            load_instagram_accounts(frm);
        }

        // "Browse Posts" button only for existing-post flow
        if (frm.doc.select_ad_type === 'Use existing post') {
            frm.add_custom_button(__('Browse Posts'), function () {
                open_posts_browser(frm);
            }, __('Ad Setup'));
        }

        // "Create on Meta" button – only if not yet created
        if (!frm.doc.creative_id && !frm.is_new()) {
            frm.add_custom_button(__('Create on Meta'), function () {
                frm.trigger('create_on_meta');
            }, __('Actions'));
        }
    },

    ad_account(frm) {
        load_facebook_pages(frm);
        load_instagram_accounts(frm);
    },

    select_ad_type(frm) {
        frm.refresh();
    },

    create_on_meta(frm) {
        frappe.confirm(
            __('This will submit the Ad Creative to Meta. Continue?'),
            function () {
                frappe.call({
                    method: 'frappe_social.ads_manager.doctype.ad_creative.ad_creative.create_creative_on_meta',
                    args: { doc_name: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Submitting to Meta…'),
                    callback(r) {
                        if (r.message && r.message.success) {
                            frappe.show_alert({
                                message: __('✓ Creative created: {0}', [r.message.creative_id]),
                                indicator: 'green'
                            }, 5);
                            frm.reload_doc();
                        } else {
                            frappe.msgprint({
                                title: __('Meta API Error'),
                                indicator: 'red',
                                message: r.message && r.message.error
                                    ? r.message.error
                                    : __('Unknown error. Check Error Log.')
                            });
                        }
                    }
                });
            }
        );
    }
});

// ============================================================================
// Facebook page / Instagram account loaders
// ============================================================================

function load_facebook_pages(frm) {
    const ad_account = frm.doc.ad_account;
    if (!ad_account) {
        frm.set_df_property('select_facebook_page', 'options', '');
        frm.refresh_field('select_facebook_page');
        return;
    }

    frm.set_df_property('select_facebook_page', 'description', __('Loading Facebook pages…'));

    frappe.call({
        method: 'frappe_social.ads_manager.doctype.ad_creative.ad_creative.get_facebook_pages',
        args: { ad_account },
        callback(r) {
            const pages = r.message || [];
            if (pages.length === 0) {
                frm.set_df_property('select_facebook_page', 'options', '');
                frm.set_df_property('select_facebook_page', 'description',
                    __('No Facebook pages found for this ad account'));
            } else {
                // Store as "Page Name (page_id)" so _extract_id() can parse it
                const options = pages.map(p => `${p.page_name} (${p.page_id})`).join('\n');
                frm.set_df_property('select_facebook_page', 'options', options);
                frm.set_df_property('select_facebook_page', 'description',
                    __('✓ {0} Facebook page(s) found', [pages.length]));
            }
            frm.refresh_field('select_facebook_page');
        },
        error(err) {
            console.error('Error loading Facebook pages:', err);
            frm.set_df_property('select_facebook_page', 'description',
                __('Error loading pages – please try again'));
            frm.refresh_field('select_facebook_page');
        }
    });
}

function load_instagram_accounts(frm) {
    const ad_account = frm.doc.ad_account;
    if (!ad_account) {
        frm.set_df_property('select_instagram_account', 'options', '');
        frm.refresh_field('select_instagram_account');
        return;
    }

    frm.set_df_property('select_instagram_account', 'description', __('Loading Instagram accounts…'));

    frappe.call({
        method: 'frappe_social.ads_manager.doctype.ad_creative.ad_creative.get_instagram_account',
        args: { ad_account },
        callback(r) {
            const accounts = r.message || [];
            if (accounts.length === 0) {
                frm.set_df_property('select_instagram_account', 'options', '');
                frm.set_df_property('select_instagram_account', 'description',
                    __('No Instagram accounts found'));
            } else {
                const options = accounts.map(a => `${a.page_name} (${a.page_id})`).join('\n');
                frm.set_df_property('select_instagram_account', 'options', options);
                frm.set_df_property('select_instagram_account', 'description',
                    __('✓ {0} Instagram account(s) found', [accounts.length]));
            }
            frm.refresh_field('select_instagram_account');
        },
        error(err) {
            console.error('Error loading Instagram accounts:', err);
            frm.set_df_property('select_instagram_account', 'description',
                __('Error loading accounts – please try again'));
            frm.refresh_field('select_instagram_account');
        }
    });
}

// ============================================================================
// Existing-post browser modal
// ============================================================================

function open_posts_browser(frm) {
    if (!frm.doc.select_facebook_page) {
        frappe.msgprint(__('Please select a Facebook Page first'));
        return;
    }
    if (!frm.doc.ad_account) {
        frappe.msgprint(__('Please select an Ad Account first'));
        return;
    }

    // Extract bare page_id from "Page Name (123456789)"
    const pageIdMatch = frm.doc.select_facebook_page.match(/\((\d+)\)$/);
    const page_id = pageIdMatch ? pageIdMatch[1] : frm.doc.select_facebook_page;

    const dialog = new frappe.ui.Dialog({
        title: __('Select Existing Post'),
        primary_action_label: __('Close'),
        primary_action() { dialog.hide(); }
    });

    dialog.$wrapper.find('.modal-body').html(`
        <div style="padding:15px;">
            <div id="posts-loading" style="text-align:center;padding:20px;">
                <i class="fa fa-spinner fa-spin"></i> ${__('Loading posts…')}
            </div>
            <div id="posts-container"></div>
        </div>
    `);
    dialog.show();

    frappe.call({
        method: 'frappe_social.ads_manager.doctype.ad_creative.ad_creative.get_existing_posts',
        args: { ad_account: frm.doc.ad_account, page_id, limit: 50 },
        callback(r) {
            document.getElementById('posts-loading').style.display = 'none';
            const posts = r.message || [];
            if (posts.length > 0) {
                render_posts_table(posts, frm, dialog);
            } else {
                document.getElementById('posts-container').innerHTML =
                    `<p style="text-align:center;color:#999;">${__('No posts found')}</p>`;
            }
        },
        error(err) {
            document.getElementById('posts-loading').style.display = 'none';
            document.getElementById('posts-container').innerHTML =
                `<p style="color:red;">${__('Error loading posts. Please try again.')}</p>`;
            console.error(err);
        }
    });
}

function render_posts_table(posts, frm, dialog) {
    let rows = posts.map(post => {
        const media = post.media_url
            ? `<img src="${post.media_url}" style="width:50px;height:50px;object-fit:cover;border-radius:4px;">`
            : `<div style="width:50px;height:50px;background:#f0f0f0;border-radius:4px;display:flex;align-items:center;justify-content:center;"><i class="fa fa-image" style="color:#999;"></i></div>`;

        const caption = (post.message || '').substring(0, 60)
            + ((post.message || '').length > 60 ? '…' : '');

        // Safely encode data into a data-attribute to avoid inline JS quoting issues
        const safePostId = (post.post_id || '').replace(/"/g, '&quot;');
        const safeMsg    = (post.message || '').replace(/"/g, '&quot;').substring(0, 500);

        return `
            <tr style="border-bottom:1px solid #eee;">
                <td style="padding:10px;">${media}</td>
                <td style="padding:10px;max-width:220px;word-wrap:break-word;">${caption || '(No caption)'}</td>
                <td style="padding:10px;font-family:monospace;font-size:12px;">${post.post_id}</td>
                <td style="padding:10px;">${post.source || 'Feed'}</td>
                <td style="padding:10px;">${post.media_type || 'Status'}</td>
                <td style="padding:10px;">${post.created_date || 'N/A'}</td>
                <td style="padding:10px;text-align:center;">
                    <button class="btn btn-xs btn-primary select-post-btn"
                        data-post-id="${safePostId}"
                        data-message="${safeMsg}">
                        ${__('Select')}
                    </button>
                </td>
            </tr>`;
    }).join('');

    const html = `
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
            <thead>
                <tr style="background:#f5f5f5;border-bottom:1px solid #ddd;">
                    <th style="padding:10px;text-align:left;">${__('Media')}</th>
                    <th style="padding:10px;text-align:left;">${__('Caption')}</th>
                    <th style="padding:10px;text-align:left;">${__('Post ID')}</th>
                    <th style="padding:10px;text-align:left;">${__('Source')}</th>
                    <th style="padding:10px;text-align:left;">${__('Type')}</th>
                    <th style="padding:10px;text-align:left;">${__('Created')}</th>
                    <th style="padding:10px;text-align:center;">${__('Action')}</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>`;

    const container = document.getElementById('posts-container');
    container.innerHTML = html;

    // Attach click handlers via event delegation (no inline JS)
    container.querySelectorAll('.select-post-btn').forEach(btn => {
        btn.addEventListener('click', function () {
            const post_id = this.dataset.postId;
            const message = this.dataset.message || '';
            select_post(post_id, message, frm, dialog);
        });
    });
}

function select_post(post_id, message, frm, dialog) {
    frm.set_value({
        'select_ad_type':   'Use existing post',
        'selected_post_id': post_id,
        'primary_text':     message
    });

    dialog.hide();
    frappe.show_alert({
        message: __('Post {0} selected', [post_id]),
        indicator: 'green'
    }, 3);
}