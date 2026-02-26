// Copyright (c) 2026, Abhishek and contributors
// For license information, please see license.txt

const OBJECTIVE_TO_PERFORMANCE_GOALS = {
    "Awareness": [
        "Maximise reach of ads", "Maximise number of impression",
        "Maximise ad recall lift", "Maximise ThruPlay views",
        "Maximise 2-second continuous video plays",
    ],
    "Traffic": [
        "Maximise number of link clicks", "Maximise number of landing page views",
        "Maximise daily unique reach", "Maximise number of conversations",
        "Maximise number of calls", "Maximise number of Instagram profile visits",
        "Maximise number of impressions",
    ],
    "Engagement": [
        "Maximise engagement with a post", "Maximise number of Page likes",
        "Maximise number of event responses", "Maximise daily unique reach",
        "Maximise number of Instagram profile visits", "Maximise number of calls",
        "Maximise reminders set", "Maximise number of conversations",
        "Maximise ThruPlay views", "Maximise 2-second continuous video plays",
    ],
    "Leads": [
        "Maximise number of leads", "Maximise number of conversion leads",
        "Maximise number of leads through messaging",
    ],
    "Sales": ["Maximise value of conversions", "Maximise number of app events"],
    "App promotion": ["Maximise number of app installs", "Maximise number of app events"],
};

// Mirror of PERFORMANCE_TO_OPTIMIZATION in meta_mappings.py
const PERFORMANCE_TO_OPTIMIZATION = {
    "Maximise reach of ads": "REACH",
    "Maximise number of impression": "IMPRESSIONS",
    "Maximise number of impressions": "IMPRESSIONS",
    "Maximise ad recall lift": "AD_RECALL_LIFT",
    "Maximise ThruPlay views": "THRUPLAY",
    "Maximise 2-second continuous video plays": "TWO_SECOND_CONTINUOUS_VIDEO_VIEWS",
    "Maximise number of link clicks": "LINK_CLICKS",
    "Maximise number of landing page views": "LANDING_PAGE_VIEWS",
    "Maximise daily unique reach": "REACH",
    "Maximise number of conversations": "CONVERSATIONS",
    "Maximise number of Instagram profile visits": "VISIT_INSTAGRAM_PROFILE",
    "Maximise number of calls": "QUALITY_CALL",
    "Maximise engagement with a post": "POST_ENGAGEMENT",
    "Maximise number of event responses": "EVENT_RESPONSES",
    "Maximise number of app events": "OFFSITE_CONVERSIONS",
    "Maximise reminders set": "REMINDERS_SET",
    "Maximise number of Page likes": "PAGE_LIKES",
    "Maximise number of leads": "LEAD_GENERATION",
    "Maximise number of conversion leads": "QUALITY_LEAD",
    "Maximise number of leads through messaging": "LEAD_GENERATION",
    "Maximise number of app installs": "APP_INSTALLS",
    "Maximise value of conversions": "VALUE",
};

frappe.ui.form.on('Ad Set', {

    refresh(frm) {
        if (frm.doc.adset_id) {
            frm.set_df_property('adset_id', 'description',
                `✓ Ad Set created on Meta: ${frm.doc.adset_id}`);
            frm.set_df_property('adset_id', 'read_only', 1);
        }
        if (frm.doc.campaign) {
            load_performance_goals(frm);
        }
        _toggle_end_date_required(frm);
    },

    onload(frm) {
        frm.set_query('campaign', () => ({
            filters: { 'custom_is_meta_ads': 1 }
        }));
    },

    campaign(frm) {
        if (frm.doc.campaign) {
            load_performance_goals(frm);
        } else {
            frm.set_value('performance_goal', '');
            frm.set_df_property('performance_goal', 'options', 'None');
        }
    },

    // ── Budget sync ────────────────────────────────────────────────────────
    amount(frm) {
        _sync_budget(frm);
    },

    budget_type_dailylifetime(frm) {
        _sync_budget(frm);
        _toggle_end_date_required(frm);
    },

    // ── Validation ────────────────────────────────────────────────────────
    validate(frm) {
        if (!frm.doc.campaign) {
            frappe.throw(__('Please select a Campaign'));
        }
        if (!frm.doc.ad_set_name) {
            frappe.throw(__('Ad Set Name is required'));
        }
        if (!frm.doc.performance_goal || frm.doc.performance_goal === 'None') {
            frappe.throw(__('Performance Goal is required'));
        }
        if (!frm.doc.amount && !frm.doc.daily_budget && !frm.doc.lifetime_budget) {
            frappe.throw(__('Either Daily Budget or Lifetime Budget is required'));
        }
        if (frm.doc.budget_type_dailylifetime === 'Lifetime Budget' && !frm.doc.end_date_and_time) {
            frappe.throw(__('End Date and Time is required for Lifetime Budget'));
        }

        // ── Frequency Control ──────────────────────────────────────────────
        const opt_goal = _get_optimization_goal(frm);

        if (frm.doc.frequency_control && ['REACH', 'THRUPLAY'].includes(opt_goal)) {
            // cint() is a Frappe global — DO NOT use frappe.utils.cint (doesn't exist)
            // Also read directly from the rendered field as a fallback for pre-migration
            const freq_field = frm.get_field('max_frequency');
            const interval_field = frm.get_field('frequency_interval_days');

            const max_freq = cint(frm.doc.max_frequency)
                || (freq_field ? cint(freq_field.get_value()) : 0);

            const interval = cint(frm.doc.frequency_interval_days)
                || (interval_field ? cint(interval_field.get_value()) : 0)
                || 7;

            if (!max_freq) {
                frappe.throw(__('Max Frequency is required when Frequency Control is set'));
            }
            if (max_freq < 1 || max_freq > 90) {
                frappe.throw(__('Max Frequency must be between 1 and 90 (got ' + max_freq + ')'));
            }
            if (interval < 1 || interval > 90) {
                frappe.throw(__('Frequency Interval Days must be between 1 and 90 (got ' + interval + ')'));
            }

            // Sync resolved values back so the server receives them correctly
            frm.set_value('max_frequency', max_freq);
            frm.set_value('frequency_interval_days', interval);
        }
    },

    before_save(frm) {
        _sync_budget(frm);

        if (frm.is_new()) {
            frappe.show_alert({
                message: __('Creating ad set on Meta Ads...'),
                indicator: 'blue'
            });
        }
    },

});

// ── Helpers ───────────────────────────────────────────────────────────────────

function _sync_budget(frm) {
    const amount = frm.doc.amount || 0;
    const type = frm.doc.budget_type_dailylifetime || 'Daily Budget';

    if (type === 'Lifetime Budget') {
        frm.set_value('lifetime_budget', amount);
        frm.set_value('daily_budget', null);
    } else {
        frm.set_value('daily_budget', amount);
        frm.set_value('lifetime_budget', null);
    }
}

function _toggle_end_date_required(frm) {
    const is_lifetime = frm.doc.budget_type_dailylifetime === 'Lifetime Budget';
    frm.set_df_property('end_date_and_time', 'reqd', is_lifetime ? 1 : 0);
    frm.set_df_property('end_date_and_time', 'bold', is_lifetime ? 1 : 0);
}

function _get_optimization_goal(frm) {
    return PERFORMANCE_TO_OPTIMIZATION[frm.doc.performance_goal] || '';
}

function load_performance_goals(frm) {
    frappe.call({
        method: 'frappe_social.ads_manager.mappings.meta_mappings.get_performance_goals_for_objective',
        args: { campaign: frm.doc.campaign },
        callback: function (r) {
            if (!r.message || !r.message.goals.length) {
                frappe.show_alert({
                    message: __('No performance goals found for this campaign objective.'),
                    indicator: 'orange'
                });
                return;
            }
            const { objective, goals } = r.message;
            frm.set_df_property('performance_goal', 'options', ['', ...goals].join('\n'));

            if (frm.doc.performance_goal && !goals.includes(frm.doc.performance_goal)) {
                frm.set_value('performance_goal', '');
                frappe.show_alert({
                    message: __(`Performance Goal reset — choose one for "${objective}"`),
                    indicator: 'orange'
                });
            }
            frappe.show_alert({
                message: __(`${goals.length} goals loaded for "${objective}"`),
                indicator: 'green'
            });
        }
    });
}
