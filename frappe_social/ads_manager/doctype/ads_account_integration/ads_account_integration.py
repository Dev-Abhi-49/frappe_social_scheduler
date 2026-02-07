"""
Ads Account Integration DocType
Handles connection and authentication with ad platforms (Facebook, Instagram)
Manages OAuth tokens
"""

from frappe.model.document import Document
from frappe.utils import now_datetime, add_to_date, get_datetime


class AdsAccountIntegration(Document):

    def get_access_token(self) -> str:
        return self.get_password("access_token") if self.access_token else None

    def get_refresh_token(self) -> str:
        return self.get_password("refresh_token") if self.refresh_token else None

    def get_page_access_token(self) -> str:
        return self.get_password("page_access_token") if self.page_access_token else None

    def get_oauth_1_secret(self):
        return self.get_password("oauth_1_secret") if self.oauth_1_secret else None

    def is_token_expired(self) -> bool:
        if not self.token_expiry:
            return False
        return get_datetime(self.token_expiry) < get_datetime(now_datetime())

    def update_tokens(self, access_token: str = None, refresh_token: str = None, expires_in: int = None):
        if access_token:
            self.access_token = access_token
        if refresh_token:
            self.refresh_token = refresh_token
        if expires_in:
            self.token_expiry = add_to_date(now_datetime(), seconds=expires_in)
        self.connection_status = "Connected"
        self.last_error = None
        self.save(ignore_permissions=True)

    def mark_as_error(self, error_message: str):
        self.connection_status = "Error"
        self.last_error = error_message
        self.last_error_time = now_datetime()
        self.save(ignore_permissions=True)
