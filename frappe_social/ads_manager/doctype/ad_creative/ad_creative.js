frappe.ui.form.on('Ad Creative', {
    refresh(frm) {
        // Show adset ID info if already created
        if (frm.doc.creative_id) {
            frm.set_df_property('creative_id', 'description',
                `✓ Ad Set created on Meta: ${frm.doc.adset_id}`);
        }

        if (frm.doc.ad_account) {
            load_facebook_pages(frm);
            load_instagram_accounts(frm);
        }

        // Show button for "Use existing post" option
        if (frm.doc.select_ad_type === 'Use existing post') {
            frm.add_custom_button('Browse Posts', function () {
                open_posts_browser(frm);
            }, 'Ad setup');
        }
    },

    ad_account(frm) {
        load_facebook_pages(frm);
        load_instagram_accounts(frm);
    },

    select_ad_type(frm) {
        frm.refresh();
    }
});

function load_facebook_pages(frm) {
    const ad_account = frm.doc.ad_account;

    if (!ad_account) {
        // Clear the field if no ad account is selected
        frm.set_df_property('select_facebook_page', 'options', []);
        frm.refresh_field('select_facebook_page');
        return;
    }

    // Show loading state
    frm.set_df_property('select_facebook_page', 'description', 'Loading Facebook pages...');

    // Fetch the ad account details and its associated pages
    frappe.call({
        method: 'frappe_social.ads_manager.doctype.ad_creative.ad_creative.get_facebook_pages',
        args: {
            ad_account: ad_account
        },
        callback: function (r) {
            if (r.message) {
                const pages = r.message;

                if (pages.length === 0) {
                    frm.set_df_property('select_facebook_page', 'options', '');
                    frm.set_df_property('select_facebook_page', 'description',
                        'No Facebook pages found for this ad account');
                } else {
                    // Build options string for the Select field with both name and ID
                    const options = pages.map(page => `${page.page_name} (${page.page_id})`).join('\n');
                    frm.set_df_property('select_facebook_page', 'options', options);
                    frm.set_df_property('select_facebook_page', 'description',
                        `✓ Found ${pages.length} Facebook page(s)`);
                }
                frm.refresh_field('select_facebook_page');
            }
        },
        error: function (err) {
            console.error('Error loading Facebook pages:', err);
            frm.set_df_property('select_facebook_page', 'description',
                'Error loading Facebook pages. Please try again.');
            frm.refresh_field('select_facebook_page');
        }
    });
}

function load_instagram_accounts(frm) {
    const ad_account = frm.doc.ad_account;

    if (!ad_account) {
        // Clear the field if no ad account is selected
        frm.set_df_property('select_instagram_account', 'options', []);
        frm.refresh_field('select_instagram_account');
        return;
    }

    // Show loading state
    frm.set_df_property('select_instagram_account', 'description', 'Loading Instagram Account...');

    // Fetch the ad account details and its associated pages
    frappe.call({
        method: 'frappe_social.ads_manager.doctype.ad_creative.ad_creative.get_instagram_account',
        args: {
            ad_account: ad_account
        },
        callback: function (r) {
            if (r.message) {
                const pages = r.message;

                if (pages.length === 0) {
                    frm.set_df_property('select_instagram_account', 'options', '');
                    frm.set_df_property('select_instagram_account', 'description',
                        'No Instagram Account found for this ad account');
                } else {
                    // Build options string for the Select field with both name and ID
                    const options = pages.map(page => `${page.page_name} (${page.page_id})`).join('\n');
                    frm.set_df_property('select_instagram_account', 'options', options);
                    frm.set_df_property('select_instagram_account', 'description',
                        `✓ Found ${pages.length} Instagram Account(s)`);
                }
                frm.refresh_field('select_instagram_account');
            }
        },
        error: function (err) {
            console.error('Error loading Instagram Account:', err);
            frm.set_df_property('select_instagram_account', 'description',
                'Error loading Instagram Account. Please try again.');
            frm.refresh_field('select_instagram_account');
        }
    });
}

// ============================================================================
// Posts Browser Modal
// ============================================================================

function open_posts_browser(frm) {
    // Validate that Facebook page is selected
    if (!frm.doc.select_facebook_page) {
        frappe.msgprint('Please select a Facebook Page first');
        return;
    }

    // Extract page ID from the selected value (format: "Page Name (page_id)")
    const pageValue = frm.doc.select_facebook_page;
    const pageIdMatch = pageValue.match(/\((\d+)\)$/);
    const page_id = pageIdMatch ? pageIdMatch[1] : pageValue;

    if (!frm.doc.ad_account) {
        frappe.msgprint('Please select an Ad Account first');
        return;
    }

    // Create modal dialog
    let dialog = new frappe.ui.Dialog({
        title: 'Select Existing Post',
        fields: [
            {
                fieldtype: 'Link',
                fieldname: 'search_text',
                label: 'Search Posts',
                options: 'Post',
                df: { fieldtype: 'Data' }
            }
        ],
        primary_action_label: 'Close',
        primary_action(values) {
            dialog.hide();
        }
    });

    // Create posts container
    let posts_html = `
        <div style="padding: 15px;">
            <div id="posts-loading" style="text-align: center; padding: 20px;">
                <p><i class="fa fa-spinner fa-spin"></i> Loading posts...</p>
            </div>
            <div id="posts-container"></div>
        </div>
    `;

    dialog.$wrapper.find('.modal-body').html(posts_html);
    dialog.show();

    // Fetch posts from backend
    frappe.call({
        method: 'frappe_social.ads_manager.doctype.ad_creative.ad_creative.get_existing_posts',
        args: {
            ad_account: frm.doc.ad_account,
            page_id: page_id,
            limit: 50
        },
        callback: function (r) {
            document.getElementById('posts-loading').style.display = 'none';

            if (r.message && r.message.length > 0) {
                render_posts_table(r.message, frm, dialog);
            } else {
                document.getElementById('posts-container').innerHTML = '<p style="text-align: center; color: #999;">No posts found</p>';
            }
        },
        error: function (err) {
            document.getElementById('posts-loading').style.display = 'none';
            document.getElementById('posts-container').innerHTML = '<p style="color: red;">Error loading posts. Please try again.</p>';
            console.error('Error fetching posts:', err);
        }
    });
}

function render_posts_table(posts, frm, dialog) {
    let html = `
        <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
            <thead>
                <tr style="background-color: #f5f5f5; border-bottom: 1px solid #ddd;">
                    <th style="padding: 10px; text-align: left;">Media</th>
                    <th style="padding: 10px; text-align: left;">Post Content</th>
                    <th style="padding: 10px; text-align: left;">Post ID</th>
                    <th style="padding: 10px; text-align: left;">Source</th>
                    <th style="padding: 10px; text-align: left;">Type</th>
                    <th style="padding: 10px; text-align: left;">Created</th>
                    <th style="padding: 10px; text-align: center;">Action</th>
                </tr>
            </thead>
            <tbody>
    `;

    posts.forEach((post) => {
        const media_preview = post.media_url
            ? `<img src="${post.media_url}" style="width: 50px; height: 50px; object-fit: cover; border-radius: 4px;">`
            : `<div style="width: 50px; height: 50px; background: #f0f0f0; border-radius: 4px; display: flex; align-items: center; justify-content: center;"><i class="fa fa-image" style="color: #999;"></i></div>`;

        const message = (post.message || '').substring(0, 50);
        const message_truncated = post.message && post.message.length > 50 ? message + '...' : message;

        html += `
            <tr style="border-bottom: 1px solid #eee; hover: background-color: #f9f9f9;">
                <td style="padding: 10px;">${media_preview}</td>
                <td style="padding: 10px; max-width: 200px; word-wrap: break-word;">${message_truncated || '(No caption)'}</td>
                <td style="padding: 10px; font-family: monospace; font-size: 12px;">${post.post_id}</td>
                <td style="padding: 10px;">${post.source || 'Feed'}</td>
                <td style="padding: 10px;">${post.media_type || 'Status'}</td>
                <td style="padding: 10px;">${post.created_date || 'N/A'}</td>
                <td style="padding: 10px; text-align: center;">
                    <button class="btn btn-xs btn-primary" onclick="select_post_for_creative('${post.post_id}', '${post.message.replace(/'/g, "\\'")}', '${frm.name}', event)">
                        Select
                    </button>
                </td>
            </tr>
        `;
    });

    html += `
            </tbody>
        </table>
    `;

    document.getElementById('posts-container').innerHTML = html;
}

function select_post_for_creative(post_id, message, form_name, event) {
    event.preventDefault();

    frappe.call({
        method: 'frappe.client.get',
        args: {
            doctype: 'Ad Creative',
            name: form_name
        },
        callback: function (r) {
            if (r.message) {
                let frm = cur_frm;

                // Store post details
                frm.set_value({
                    'select_ad_type': 'Use existing post',
                    'selected_post_id': post_id,
                    'primary_text': message || ''
                });

                frappe.msgprint(`Post ${post_id} selected successfully!`);

                // Close all dialogs
                document.querySelectorAll('.modal').forEach(modal => {
                    let instance = $(modal).data('bs.modal');
                    if (instance) instance.hide();
                });
            }
        }
    });
}
