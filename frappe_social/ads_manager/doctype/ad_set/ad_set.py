# Copyright (c) 2026, Abhishek and contributors
# For license information, please see license.txt

import frappe
import logging
from frappe import _
from frappe.model.document import Document
from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider
from frappe_social.ads_manager.mappings.meta_mappings import (
    PERFORMANCE_TO_OPTIMIZATION,
    OPTIMIZATION_TO_BILLING,
)

logger = logging.getLogger(__name__)


class AdSet(Document):
    """
    Ad Set Document — Meta Marketing API v24.0
    https://developers.facebook.com/docs/marketing-api/reference/ad-account/adsets/v24.0
    """

    def before_save(self):
        if self.is_new() or not self.adset_id:
            self._create_meta_ad_set()

    # ──────────────────────────────────────────────────────────────────────────
    # Orchestrator
    # ──────────────────────────────────────────────────────────────────────────

    def _create_meta_ad_set(self):
        try:
            if not self.campaign:
                frappe.throw(_("Campaign is required to create an ad set"))
            if not self.ad_set_name:
                frappe.throw(_("Ad Set Name is required"))
            if not self.performance_goal or self.performance_goal == "None":
                frappe.throw(_("Performance Goal is required"))

            campaign_doc = frappe.get_doc("Marketing Campaign", self.campaign)
            logger.info(f"Campaign doc: {campaign_doc.name}")
            logger.info(f"Campaign ID: {campaign_doc.custom_facebook_campaign_id}")
            logger.info(f"Account: {campaign_doc.custom_select_facebook_ad_account}")

            if not campaign_doc.custom_facebook_campaign_id:
                frappe.throw(_("Selected campaign has no Meta campaign ID"))
            if not campaign_doc.custom_select_facebook_ad_account:
                frappe.throw(_("Selected campaign has no associated ad account"))

            provider = MetaAdsProvider(campaign_doc.custom_select_facebook_ad_account)
            payload = self._build_ad_set_payload(campaign_doc)

            logger.info(f"Payload being sent to Meta:\n{frappe.as_json(payload, indent=2)}")

            result = provider.create_ad_set(payload)
            logger.info(f"Raw result from Meta: {result}")

            if result.success:
                self.adset_id = result.adset_id
                logger.info(f"✓ Ad Set created successfully: {result.adset_id}")
                frappe.msgprint(
                    _("Ad Set created successfully on Meta Ads. ID: {0}").format(result.adset_id),
                    alert=True,
                )
            else:
                error_msg = result.error_message or "Unknown error from Meta API"
                logger.error(f"Failed to create ad set: {error_msg}")
                frappe.throw(_("Failed to create ad set on Meta Ads: {0}").format(error_msg))

        except frappe.exceptions.ValidationError:
            # Re-raise Frappe validation errors directly — don't double-wrap them
            raise
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Exception in _create_meta_ad_set: {error_msg}")
            logger.error(frappe.get_traceback())
            frappe.log_error(frappe.get_traceback(), "Ad Set Creation Error")
            frappe.throw(_("Failed to create ad set: {0}").format(error_msg))

    # ──────────────────────────────────────────────────────────────────────────
    # Payload Builder
    # ──────────────────────────────────────────────────────────────────────────

    def _build_ad_set_payload(self, campaign_doc) -> dict:
        """
        Build POST /act_{ad_account_id}/adsets payload.
        Uses getattr() for any fields that may not yet exist in the DB schema
        (i.e. added to JSON but bench migrate not yet run).
        """

        # ── Safely read fields that may be missing pre-migration ────────────
        max_frequency           = getattr(self, "max_frequency", None)
        frequency_interval_days = getattr(self, "frequency_interval_days", 7) or 7
        dynamic_creative        = getattr(self, "dynamic_creative", None)
        optimization_sub_event  = getattr(self, "optimization_sub_event", None)
        multi_opt_weight        = getattr(self, "multi_optimization_goal_weight", None)
        destination_type        = getattr(self, "destination_type", None)
        delivery_type           = getattr(self, "delivery_type", None)
        daily_spend_cap         = getattr(self, "daily_spend_cap", None)
        lifetime_spend_cap      = getattr(self, "lifetime_spend_cap", None)
        daily_min_spend         = getattr(self, "daily_min_spend_target", None)
        lifetime_min_spend      = getattr(self, "lifetime_min_spend_target", None)
        existing_cust_pct       = getattr(self, "existing_customer_budget_percentage", None)
        max_budget_pct          = getattr(self, "max_budget_spend_percentage", None)
        min_budget_pct          = getattr(self, "min_budget_spend_percentage", None)
        recurring               = getattr(self, "recurring_budget_semantics", None)
        check_mrux              = getattr(self, "check_mrux", None)
        budget_scheduling       = getattr(self, "budget_scheduling", None)

        # ── 1. Optimization Goal ────────────────────────────────────────────
        optimization_goal = PERFORMANCE_TO_OPTIMIZATION.get(self.performance_goal)
        if not optimization_goal:
            frappe.throw(
                _("No API optimization goal found for performance goal: {0}").format(
                    self.performance_goal
                )
            )

        # ── 2. Billing Event ────────────────────────────────────────────────
        billing_event = self.billing_event or OPTIMIZATION_TO_BILLING.get(
            optimization_goal, "IMPRESSIONS"
        )

        # ── 3. Bid Strategy ─────────────────────────────────────────────────
        bid_strategy = self.bid_strategy or "LOWEST_COST_WITHOUT_CAP"

        # ── 4. Budget ───────────────────────────────────────────────────────
        budget_type = self.budget_type_dailylifetime or "Daily Budget"

        if budget_type == "Lifetime Budget":
            raw_budget = self.amount or self.lifetime_budget
            if not raw_budget:
                frappe.throw(_("Lifetime Budget amount is required"))
            lifetime_budget_cents = int(float(raw_budget) * 100)
        else:
            raw_budget = self.amount or self.daily_budget
            if not raw_budget:
                frappe.throw(_("Daily Budget amount is required"))
            daily_budget_cents = int(float(raw_budget) * 100)
            if daily_budget_cents < 1000:
                frappe.throw(
                    _("Daily budget too low. Minimum ~$10 (1000 cents) is recommended.")
                )

        # ── 5. Targeting ────────────────────────────────────────────────────
        targeting = self._build_targeting()

        # ── 6. Core Required Fields ─────────────────────────────────────────
        payload = {
            "name": self.ad_set_name,
            "campaign_id": campaign_doc.custom_facebook_campaign_id,
            "optimization_goal": optimization_goal,
            "billing_event": billing_event,
            "bid_strategy": bid_strategy,
            "targeting": targeting,
            "status": "ACTIVE" if self.enable_ad_set else "PAUSED",
        }

        if budget_type == "Lifetime Budget":
            payload["lifetime_budget"] = lifetime_budget_cents
        else:
            payload["daily_budget"] = daily_budget_cents

        # ── 7. Bid Amount ────────────────────────────────────────────────────
        if bid_strategy in ["LOWEST_COST_WITH_BID_CAP", "COST_CAP"]:
            if not self.bid_amount:
                frappe.throw(
                    _("Bid Amount is required for bid strategy: {0}").format(bid_strategy)
                )
            payload["bid_amount"] = int(float(self.bid_amount) * 100)

        # ── 8. Start / End Time ─────────────────────────────────────────────
        start = self.start_time or self.start_date_and_time
        end   = self.end_time   or self.end_date_and_time

        if start:
            payload["start_time"] = self._to_iso(start)

        if budget_type == "Lifetime Budget":
            if not end:
                frappe.throw(_("End Time is required when using Lifetime Budget"))
            payload["end_time"] = self._to_iso(end)
        elif end:
            payload["end_time"] = self._to_iso(end)

        # ── 9. time_start / time_stop (Reach & Frequency) ───────────────────
        if self.time_start:
            payload["time_start"] = self._to_iso(self.time_start)
        if self.time_stop:
            payload["time_stop"] = self._to_iso(self.time_stop)

        # ── 10. Destination Type ────────────────────────────────────────────
        if destination_type:
            payload["destination_type"] = destination_type

        # ── 11. Dynamic Creative ────────────────────────────────────────────
        if dynamic_creative:
            payload["is_dynamic_creative"] = True

        # ── 12. Advanced Budget Controls ────────────────────────────────────
        if daily_spend_cap:
            payload["daily_spend_cap"] = int(float(daily_spend_cap) * 100)
        if lifetime_spend_cap:
            payload["lifetime_spend_cap"] = int(float(lifetime_spend_cap) * 100)
        if daily_min_spend:
            payload["daily_min_spend_target"] = int(float(daily_min_spend) * 100)
        if lifetime_min_spend:
            payload["lifetime_min_spend_target"] = int(float(lifetime_min_spend) * 100)
        if existing_cust_pct:
            payload["existing_customer_budget_percentage"] = int(existing_cust_pct)
        if max_budget_pct:
            payload["max_budget_spend_percentage"] = int(max_budget_pct)
        if min_budget_pct:
            payload["min_budget_spend_percentage"] = int(min_budget_pct)
        if recurring:
            payload["recurring_budget_semantics"] = True

        # ── 13. Frequency Control Specs ─────────────────────────────────────
        # max_frequency field may not exist pre-migration → guarded by getattr above
        if (
            self.frequency_control
            and max_frequency
            and optimization_goal in ["REACH", "THRUPLAY"]
        ):
            max_freq = int(max_frequency)
            interval = int(frequency_interval_days)

            if not (1 <= max_freq <= 90):
                frappe.throw(
                    _("Max Frequency must be between 1 and 90 (got {0})").format(max_freq)
                )
            if not (1 <= interval <= 90):
                frappe.throw(
                    _("Frequency Interval Days must be between 1 and 90 (got {0})").format(interval)
                )

            payload["frequency_control_specs"] = [
                {
                    "event": "IMPRESSIONS",
                    "interval_days": interval,
                    "max_frequency": max_freq,
                }
            ]

        # ── 14. Optimization Sub Event ──────────────────────────────────────
        if optimization_sub_event and optimization_sub_event != "NONE":
            payload["optimization_sub_event"] = optimization_sub_event

        # ── 15. Multi Optimization Goal Weight ──────────────────────────────
        if multi_opt_weight and multi_opt_weight != "UNDEFINED":
            payload["multi_optimization_goal_weight"] = multi_opt_weight

        # ── 16. Pacing Type ─────────────────────────────────────────────────
        if delivery_type:
            payload["pacing_type"] = ["standard"]

        # ── 17. Tune for Category ────────────────────────────────────────────
        if check_mrux:
            payload["tune_for_category"] = "FINANCIAL_PRODUCTS_SERVICES"

        # ── 18. Budget Schedule Specs ────────────────────────────────────────
        if budget_scheduling and self.time_period_for_budget_increase:
            specs = []
            for row in self.time_period_for_budget_increase:
                spec = {}
                if row.get("time_start"):
                    spec["time_start"] = self._to_unix(row.time_start)
                if row.get("time_end"):
                    spec["time_end"] = self._to_unix(row.time_end)
                if row.get("budget_value"):
                    spec["budget_value"] = int(float(row.budget_value) * 100)
                    spec["budget_value_type"] = "ABSOLUTE"
                if spec:
                    specs.append(spec)
            if specs:
                payload["budget_schedule_specs"] = specs

        logger.info("Meta AdSet Payload:\n" + frappe.as_json(payload, indent=2))
        return payload

    # ──────────────────────────────────────────────────────────────────────────
    # Targeting Builder
    # ──────────────────────────────────────────────────────────────────────────

    def _build_targeting(self) -> dict:
        targeting = {
            "geo_locations": {"countries": ["IN"]},
            "age_min": self.age_min or 18,
            "age_max": self.age_max or 65,
        }

        if self.geo_location:
            country_code = (
                frappe.db.get_value("Country", self.geo_location, "code") or "IN"
            )
            targeting["geo_locations"]["countries"] = [country_code.upper()]

        if self.gender == "Male":
            targeting["genders"] = [1]
        elif self.gender == "Female":
            targeting["genders"] = [2]

        if self.manual_placement:
            publisher_platforms = []
            if self.facebook:
                publisher_platforms.append("facebook")
            if self.instgram:
                publisher_platforms.append("instagram")
            if self.messenger:
                publisher_platforms.append("messenger")
            if self.audience_network:
                publisher_platforms.append("audience_network")

            if publisher_platforms:
                targeting["publisher_platforms"] = publisher_platforms

            if self.devices == "Mobile":
                targeting["device_platforms"] = ["mobile"]
            elif self.devices == "Desktop":
                targeting["device_platforms"] = ["desktop"]

        return targeting

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _to_iso(dt) -> str:
        if hasattr(dt, "isoformat"):
            return dt.isoformat()
        return str(dt)

    @staticmethod
    def _to_unix(dt) -> int:
        import datetime, calendar
        if isinstance(dt, datetime.date) and not isinstance(dt, datetime.datetime):
            dt = datetime.datetime.combine(dt, datetime.time.min)
        if isinstance(dt, datetime.datetime):
            return int(calendar.timegm(dt.timetuple()))
        return int(dt)
