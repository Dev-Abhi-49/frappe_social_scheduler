frappe.ui.form.on('Ads Analytics', {
    refresh: function (frm) {
        // Disable editing of read-only fields
        frm.set_df_property('ads_account_integration', 'read_only', 1);
        frm.set_df_property('analytics_date', 'read_only', 1);
        frm.set_df_property('last_synced', 'read_only', 1);
        frm.set_df_property('sync_status', 'read_only', 1);
        frm.refresh_field('ads_account_integration');
        frm.refresh_field('analytics_date');
        frm.refresh_field('last_synced');
        frm.refresh_field('sync_status');

        // Add custom styling for better visualization
        add_analytics_summary(frm);
    }
});

function add_analytics_summary(frm) {
    // Create a summary section
    let summary_html = `
        <div style="padding: 20px; background: #f8f9fa; border-radius: 8px; margin-bottom: 20px;">
            <h4 style="margin-bottom: 15px; color: #333;">📊 Campaign Performance Summary</h4>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
    `;

    // Key metrics to display
    const metrics = [
        {
            label: 'Total Spend',
            value: format_currency(frm.doc.spend),
            icon: '💰',
            color: '#ff6b6b'
        },
        {
            label: 'Impressions',
            value: format_number(frm.doc.impressions),
            icon: '👁️',
            color: '#4ecdc4'
        },
        {
            label: 'Clicks',
            value: format_number(frm.doc.clicks),
            icon: '🖱️',
            color: '#45b7d1'
        },
        {
            label: 'Reach',
            value: format_number(frm.doc.reach),
            icon: '📢',
            color: '#96ceb4'
        },
        {
            label: 'CTR',
            value: (frm.doc.ctr || 0).toFixed(2) + '%',
            icon: '📈',
            color: '#ffeaa7'
        },
        {
            label: 'CPC',
            value: format_currency(frm.doc.cpc),
            icon: '💵',
            color: '#dfe6e9'
        },
        {
            label: 'Conversions',
            value: format_number(frm.doc.conversions),
            icon: '✅',
            color: '#a29bfe'
        },
        {
            label: 'Conversion Rate',
            value: (frm.doc.conversion_rate || 0).toFixed(2) + '%',
            icon: '⭐',
            color: '#e17055'
        }
    ];

    metrics.forEach(metric => {
        summary_html += `
            <div style="
                background: white;
                padding: 15px;
                border-radius: 6px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                border-left: 4px solid ${metric.color};
            ">
                <div style="font-size: 24px; margin-bottom: 8px;">${metric.icon}</div>
                <div style="font-size: 14px; color: #666; margin-bottom: 5px;">${metric.label}</div>
                <div style="font-size: 20px; font-weight: bold; color: ${metric.color};">${metric.value}</div>
            </div>
        `;
    });

    summary_html += `
            </div>
        </div>
    `;

    // Add campaign overview section
    if (frm.doc.total_campaigns > 0) {
        summary_html += `
            <div style="padding: 15px; background: white; border-radius: 8px; border: 1px solid #ddd;">
                <h5 style="margin-top: 0;">📋 Campaign Overview</h5>
                <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; text-align: center;">
                    <div>
                        <div style="font-size: 24px; font-weight: bold; color: #2d5016;">${frm.doc.active_campaigns || 0}</div>
                        <div style="font-size: 12px; color: #666;">Active Campaigns</div>
                    </div>
                    <div>
                        <div style="font-size: 24px; font-weight: bold; color: #0066cc;">${frm.doc.total_campaigns || 0}</div>
                        <div style="font-size: 12px; color: #666;">Total Campaigns</div>
                    </div>
                    <div>
                        <div style="font-size: 24px; font-weight: bold; color: #ff6b6b;">${frm.doc.adsets_count || 0}</div>
                        <div style="font-size: 12px; color: #666;">Ad Sets</div>
                    </div>
                    <div>
                        <div style="font-size: 24px; font-weight: bold; color: #a29bfe;">${frm.doc.ads_count || 0}</div>
                        <div style="font-size: 12px; color: #666;">Ads</div>
                    </div>
                </div>
            </div>
        `;
    }

    summary_html += '</div>';

    // Find or create the summary container
    let summary_container = frm.page.page_content.find('.analytics-summary-container');

    if (summary_container.length === 0) {
        // Create new container if it doesn't exist
        frm.page.page_content.prepend(`<div class="analytics-summary-container"></div>`);
        summary_container = frm.page.page_content.find('.analytics-summary-container');
    }

    // Update the summary HTML
    summary_container.html(summary_html);

    // Add button to view account integration
    if (!frm.page.page_content.find('.btn-view-account').length) {
        frm.page.add_inner_button(__('View Account'), function () {
            frappe.set_route('Form', 'Ads Account Integration', frm.doc.ads_account_integration);
        });
    }
}

function format_currency(value) {
    if (!value) return '₹0.00';
    return '₹' + parseFloat(value).toFixed(2);
}

function format_number(value) {
    if (!value) return '0';
    let num = parseInt(value);
    if (num >= 1000000) {
        return (num / 1000000).toFixed(1) + 'M';
    } else if (num >= 1000) {
        return (num / 1000).toFixed(1) + 'K';
    }
    return num.toString();
}
