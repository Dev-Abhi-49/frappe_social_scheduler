// // Copyright (c) 2026, Frappe Social and contributors
// // For license information, please see license.txt

frappe.ui.form.on('Social Settings', {
    //     refresh: function (frm) {
    //          frm.set_intro(__('We are in early stage of developement. Please be patient for more platforms and features.'));
    //         // Add helpful links
    //         frm.add_custom_button(__('View Integrations'), function () {
    //             frappe.set_route('List', 'Social Integration');
    //         }, __('Actions'));

    //         frm.add_custom_button(__('View Scheduled Posts'), function () {
    //             frappe.set_route('List', 'Social Post', { status: 'Scheduled' });
    //         }, __('Actions'));

    //         // Reset counters button
    //         frm.add_custom_button(__('Reset Daily Counters'), function () {
    //             frappe.confirm(
    //                 __('Reset all daily post counters and quota tracking?'),
    //                 function () {
    //                     frm.set_value('twitter_posts_today', 0);
    //                     frm.set_value('instagram_posts_today', 0);
    //                     frm.set_value('youtube_quota_used', 0);
    //                     frm.save();
    //                     frappe.show_alert({ message: __('Counters reset'), indicator: 'green' });
    //                 }
    //             );
    //         }, __('Actions'));

    //         // Show quota usage
    //         frm.trigger('show_quota_dashboard');
    //     },

    //     twitter_tier: function (frm) {
    //         // Update daily limit based on tier
    //         let limits = { 'Free': 17, 'Basic': 100, 'Pro': 1000, 'Enterprise': 10000 };
    //         frm.set_value('twitter_daily_limit', limits[frm.doc.twitter_tier] || 17);
    //     },

    //     show_quota_dashboard: function (frm) {
    //         let html = `
    //             <div class="row" style="margin-top: 15px;">
    //                 <div class="col-sm-4">
    //                     <div class="stat-box">
    //                         <h6>Twitter Posts Today</h6>
    //                         <h3>${frm.doc.twitter_posts_today || 0} / ${frm.doc.twitter_daily_limit || 17}</h3>
    //                     </div>
    //                 </div>
    //                 <div class="col-sm-4">
    //                     <div class="stat-box">
    //                         <h6>Instagram Posts Today</h6>
    //                         <h3>${frm.doc.instagram_posts_today || 0} / ${frm.doc.instagram_daily_limit || 25}</h3>
    //                     </div>
    //                 </div>
    //                 <div class="col-sm-4">
    //                     <div class="stat-box">
    //                         <h6>YouTube Quota Used</h6>
    //                         <h3>${frm.doc.youtube_quota_used || 0} / ${frm.doc.youtube_quota_limit || 10000}</h3>
    //                     </div>
    //                 </div>
    //             </div>
    //         `;
    //         frm.dashboard.set_headline('');
    //         frm.dashboard.add_section(html);
    //     }
});
