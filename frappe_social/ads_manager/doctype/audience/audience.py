# Copyright (c) 2026, Abhishek and contributors
# For license information, please see license.txt

import hashlib
import logging

import frappe
from frappe import _
from frappe.model.document import Document
from frappe_social.ads_manager.providers.meta_ads import MetaAdsProvider

logger = logging.getLogger(__name__)


class Audience(Document):

    def before_save(self):
        if self.is_new() or not self.audience_id:
            self._create_meta_audience()

    # ── Create audience on Meta ───────────────────────────────────────────

    def _create_meta_audience(self):
        try:
            self._validate_fields()

            provider = MetaAdsProvider(self.select_ad_account)
            payload = self._build_audience_payload()

            logger.info(f"Creating audience '{self.audience_name}' with payload: {payload}")
            result = provider.create_audience(payload)

            if not result.success:
                frappe.throw(_("Failed to create audience on Meta: {0}").format(result.error_message))

            self.audience_id = result.audience_id
            self.status = "New"
            logger.info(f"✓ Audience created: {result.audience_id}")
            frappe.msgprint(
                _("Audience created on Meta. ID: {0}").format(result.audience_id),
                alert=True,
            )

            # For CRM audiences, upload members right after creation
            if self.subtype == "CUSTOM" and self.crm_data:
                self._upload_crm_users(provider, result.audience_id)

        except frappe.ValidationError:
            raise
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Custom Audience Creation Error")
            frappe.throw(_("Failed to create audience: {0}").format(str(e)))

    # ── Field validation ─────────────────────────────────────────────────

    def _validate_fields(self):
        if not self.audience_name:
            frappe.throw(_("Audience Name is required"))
        if not self.select_ad_account:
            frappe.throw(_("Ad Account is required"))
        if not self.subtype:
            frappe.throw(_("Audience Type is required"))

        if self.subtype == "CUSTOM":
            if not self.schema_type:
                frappe.throw(_("Match Key (schema type) is required for Customer List audience"))
            if not self.crm_data:
                frappe.throw(_("Customer data is required for Customer List audience"))

        elif self.subtype == "WEBSITE":
            if not self.pixel_id:
                frappe.throw(_("Pixel ID is required for Website audience"))
            if not self.pixel_event:
                frappe.throw(_("Pixel Event is required for Website audience"))

        elif self.subtype == "APP":
            if not self.application_id:
                frappe.throw(_("Application ID is required for App audience"))
            if not self.app_event:
                frappe.throw(_("App Event is required for App audience"))

        elif self.subtype == "ENGAGEMENT":
            if not self.engagement_source_type:
                frappe.throw(_("Engagement Source Type is required"))
            if not self.engagement_source_id:
                frappe.throw(_("Page / Instagram Account ID is required"))

        elif self.subtype == "LOOKALIKE":
            if not self.origin_audience_id:
                frappe.throw(_("Source Audience is required for Lookalike"))
            if not self.lookalike_country:
                frappe.throw(_("Target Country is required for Lookalike"))
            if not self.lookalike_ratio or float(self.lookalike_ratio) <= 0:
                frappe.throw(_("Lookalike ratio must be between 0.01 and 0.20"))

    # ── Build payload per subtype ────────────────────────────────────────

    def _build_audience_payload(self) -> dict:
        base = {
            "name": self.audience_name,
            "subtype": self.subtype,
            "description": self.description or "",
        }

        if self.subtype == "CUSTOM":
            base["customer_file_source"] = self.customer_file_source or "USER_PROVIDED_ONLY"

        elif self.subtype == "WEBSITE":
            retention_seconds = int(self.retention_days or 30) * 86400
            base.update({
                "pixel_id": self.pixel_id,
                "retention_days": int(self.retention_days or 30),
                "rule": {
                    "inclusions": {
                        "operator": "or",
                        "rules": [{
                            "event_sources": [{"id": self.pixel_id, "type": "pixel"}],
                            "retention_seconds": retention_seconds,
                            "filter": {
                                "operator": "and",
                                "filters": [{
                                    "field": "event",
                                    "operator": "eq",
                                    "value": self.pixel_event,
                                }]
                            }
                        }]
                    }
                }
            })

        elif self.subtype == "APP":
            retention_seconds = int(self.retention_days or 30) * 86400
            base.update({
                "retention_days": int(self.retention_days or 30),
                "rule": {
                    "inclusions": {
                        "operator": "or",
                        "rules": [{
                            "event_sources": [{"id": self.application_id, "type": "app"}],
                            "retention_seconds": retention_seconds,
                            "filter": {
                                "operator": "and",
                                "filters": [{
                                    "field": "event",
                                    "operator": "eq",
                                    "value": self.app_event,
                                }]
                            }
                        }]
                    }
                }
            })

        elif self.subtype == "ENGAGEMENT":
            retention_seconds = int(self.retention_days or 30) * 86400
            event_map = {
                "page": "page_engaged",
                "instagram_business": "ig_business_profile_all",
                "lead_generation": "lead_generation_submitted",
            }
            base.update({
                "retention_days": int(self.retention_days or 30),
                "rule": {
                    "inclusions": {
                        "operator": "or",
                        "rules": [{
                            "event_sources": [{
                                "id": self.engagement_source_id,
                                "type": self.engagement_source_type,
                            }],
                            "retention_seconds": retention_seconds,
                            "filter": {
                                "operator": "and",
                                "filters": [{
                                    "field": "event",
                                    "operator": "eq",
                                    "value": event_map.get(self.engagement_source_type, "page_engaged"),
                                }]
                            }
                        }]
                    }
                }
            })

        elif self.subtype == "LOOKALIKE":
            # Get source audience's Meta audience_id
            source_meta_id = frappe.db.get_value(
                "Audience", self.origin_audience_id, "audience_id"
            )
            if not source_meta_id:
                frappe.throw(_("Source audience has no Meta Audience ID. Create it on Meta first."))

            country_code = frappe.db.get_value(
                "Country", self.lookalike_country, "code"
            ) or "IN"

            base.update({
                "origin_audience_id": source_meta_id,
                "lookalike_spec": {
                    "type": self.lookalike_type or "similarity",
                    "ratio": float(self.lookalike_ratio or 0.01),
                    "country": country_code.upper(),
                }
            })

        return base

    # ── Upload CRM users (hashed) ────────────────────────────────────────

    def _upload_crm_users(self, provider, audience_id: str):
        raw_lines = [line.strip() for line in self.crm_data.splitlines() if line.strip()]
        if not raw_lines:
            return

        schema_map = {
            "EMAIL": ["EMAIL"],
            "PHONE": ["PHONE"],
            "EMAIL_AND_PHONE": ["EMAIL", "PHONE"],
        }
        schema = schema_map.get(self.schema_type, ["EMAIL"])

        # SHA-256 hash each value before sending
        def sha256(value):
            return hashlib.sha256(value.lower().strip().encode("utf-8")).hexdigest()

        if self.schema_type == "EMAIL_AND_PHONE":
            # Expect "email,phone" per line
            hashed_data = []
            for line in raw_lines:
                parts = line.split(",")
                if len(parts) == 2:
                    hashed_data.append([sha256(parts[0]), sha256(parts[1])])
        else:
            hashed_data = [[sha256(line)] for line in raw_lines]

        result = provider.add_users_to_audience(audience_id, schema, hashed_data)
        added = result.get("num_received", 0)
        invalid = result.get("num_invalid_entries", 0)

        logger.info(f"CRM upload: {added} received, {invalid} invalid")
        frappe.msgprint(
            _("Customer list uploaded: {0} added, {1} invalid entries.").format(added, invalid),
            alert=True,
        )
