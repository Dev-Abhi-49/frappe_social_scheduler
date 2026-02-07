"""
Token Service - Handles OAuth token refresh
"""

import frappe
from frappe.utils import now_datetime, add_to_date
from typing import Dict, Any
from frappe_social.frappe_social.providers import get_provider


class TokenService:
    
    @staticmethod
    def refresh_token(integration_name: str) -> Dict[str, Any]:
        """Refresh OAuth token for an integration"""
        integration = frappe.get_doc("Social Integration", integration_name)
        
        if not integration.enabled:
            return {'success': False, 'error_message': 'Integration disabled'}
        
        try:
            provider = get_provider(integration.platform)(integration_name)
            result = provider.refresh_token(integration_name)
            
            if result.success:
                integration.access_token = result.access_token
                if result.refresh_token:
                    integration.refresh_token = result.refresh_token
                if result.expires_in:
                    integration.token_expiry = add_to_date(now_datetime(), seconds=result.expires_in)
                integration.connection_status = "Connected"
                integration.last_error = None
                integration.save(ignore_permissions=True)
                frappe.db.commit()
                return {'success': True}
            else:
                integration.connection_status = "Expired"
                integration.last_error = result.error_message
                integration.last_error_time = now_datetime()
                integration.save(ignore_permissions=True)
                frappe.db.commit()
                return {'success': False, 'error_message': result.error_message}
                
        except Exception as e:
            frappe.log_error(f"Token refresh failed for {integration_name}: {e}", "Token Refresh Error")
            return {'success': False, 'error_message': str(e)}
    
    @staticmethod
    def check_token_validity(integration_name: str) -> Dict[str, Any]:
        """Check if token is valid and not expired"""
        integration = frappe.get_doc("Social Integration", integration_name)
        
        is_expired = integration.is_token_expired()
        days_until_expiry = None
        
        if integration.token_expiry:
            delta = integration.token_expiry - now_datetime()
            days_until_expiry = delta.days
        
        return {
            'valid': not is_expired,
            'expires_in_days': days_until_expiry,
            'connection_status': integration.connection_status
        }
