// frappe.ui.form.on('Marketing Campaign', {
//     refresh: function(frm) {
//         toggle_ads_section_visibility(frm);
//     },

//     after_save: function(frm) {
//         // Check if no ads are selected
//         const any_ads_selected = frm.doc.custom_is_meta_ads || 
//                                  frm.doc.custom_is_google_ads || 
//                                  frm.doc.custom_is_linkedin_ads || 
//                                  frm.doc.custom_is_twitter_ads;

//         if (!any_ads_selected && !frm.is_new()) {
//             // Reload the form to apply visibility changes
//             frappe.set_route('Form', 'Marketing Campaign', frm.doc.name);
//         } else {
//             toggle_ads_section_visibility(frm);
//         }
//     },

//     custom_is_meta_ads: function(frm) {
//         toggle_ads_section_visibility(frm);
//     },

//     custom_is_google_ads: function(frm) {
//         toggle_ads_section_visibility(frm);
//     },

//     custom_is_linkedin_ads: function(frm) {
//         toggle_ads_section_visibility(frm);
//     },

//     custom_is_twitter_ads: function(frm) {
//         toggle_ads_section_visibility(frm);
//     }
// });

// function toggle_ads_section_visibility(frm) {
//     const any_ads_selected = frm.doc.custom_is_meta_ads || 
//                              frm.doc.custom_is_google_ads || 
//                              frm.doc.custom_is_linkedin_ads || 
//                              frm.doc.custom_is_twitter_ads;

//     if (frm.is_new()) {
//         show_ads_section(frm);
//     } else {
//         if (any_ads_selected) {
//             show_ads_section(frm);
//         } else {
//             hide_ads_section(frm);
//         }
//     }
// }

// function show_ads_section(frm) {
//     frm.set_df_property('custom_is_meta_ads', 'hidden', 0);
//     frm.set_df_property('custom_is_google_ads', 'hidden', 0);
//     frm.set_df_property('custom_is_linkedin_ads', 'hidden', 0);
//     frm.set_df_property('custom_is_twitter_ads', 'hidden', 0);
// }

// function hide_ads_section(frm) {
//     frm.set_df_property('custom_is_meta_ads', 'hidden', 1);
//     frm.set_df_property('custom_is_google_ads', 'hidden', 1);
//     frm.set_df_property('custom_is_linkedin_ads', 'hidden', 1);
//     frm.set_df_property('custom_is_twitter_ads', 'hidden', 1);
// }
