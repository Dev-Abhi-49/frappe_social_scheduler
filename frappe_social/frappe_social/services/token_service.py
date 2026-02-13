"""
Token Service - Handles OAuth token refresh
"""

import frappe
from frappe.utils import now_datetime, add_to_date
from typing import Dict, Any
from frappe_social.frappe_social.providers import get_provider
from frappe_social.frappe_social.api.oauth import refresh_youtube_token

class TokenService:
    
    @staticmethod
    def refresh_token(integration_name: str) -> Dict[str, Any]:
        """Refresh OAuth token for an integration"""
        integration = frappe.get_doc("Social Integration", integration_name)
        
        if not integration.enabled:
            return {'success': False, 'error_message': 'Integration disabled'}
        
        if integration.platform == "YouTube":
            result = refresh_youtube_token(integration_name)
            
            return {
                'success': result.get('success', False),
                'error_message': result.get('error', '') if not result.get('success') else None
            }
        
        try:
            provider = get_provider(integration.platform)(integration_name)
            
            if not hasattr(provider, 'refresh_token'):
                return {
                    'success': False, 
                    'error_message': f'{integration.platform} does not support token refresh'
                }
                
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
            
            integration.connection_status = "Error"
            integration.last_error = error_msg
            integration.last_error_time = now_datetime()
            integration.save(ignore_permissions=True)
            frappe.db.commit()
            
            return {'success': False, 'error_message': str(e)}
    
    @staticmethod
    def check_token_validity(integration_name: str) -> Dict[str, Any]:
        """Check if token is valid and not expired"""
        integration = frappe.get_doc("Social Integration", integration_name)
        
        is_expired = integration.is_token_expired() if hasattr(integration, 'is_token_expired') else False
        days_until_expiry = None
        
        if integration.token_expiry:
            delta = integration.token_expiry - now_datetime()
            days_until_expiry = delta.days
            hours_until_expiry = delta.total_seconds() / 3600
        else:
            hours_until_expiry = None
        
        return {
            'valid': not is_expired,
            'expires_in_days': days_until_expiry,
            'expires_in_hours': hours_until_expiry,
            'connection_status': integration.connection_status,
            'platform': integration.platform
        }
    
    @staticmethod
    def auto_refresh_if_needed(integration_name: str) -> bool:
        """
        Auto-refresh token if expired or expiring soon
        Returns True if token is valid, False otherwise
        """
        try:
            integration = frappe.get_doc("Social Integration", integration_name)
            
            # YouTube-specific auto-refresh
            if integration.platform == "YouTube":
                return auto_refresh_if_expired(integration)
            
            # For other platforms, check expiry
            if integration.token_expiry:
                time_until_expiry = frappe.utils.time_diff_in_seconds(
                    integration.token_expiry, 
                    now_datetime()
                )
                
                # If less than 1 day remaining, refresh
                if time_until_expiry < 86400:  # 24 hours
                    result = TokenService.refresh_token(integration_name)
                    return result.get('success', False)
            
            return True
            
        except Exception as e:
            frappe.log_error(f"Auto-refresh check failed: {str(e)}", "Token Auto-Refresh")
            return False