"""
Post Service - Handles publishing workflow
"""

import re
import frappe
from typing import Dict, Any
from frappe_social.frappe_social.providers import get_provider
from frappe_social.frappe_social.providers.base import PublishResult
from frappe.utils import now_datetime


def strip_html(html_content: str) -> str:
    if not html_content:
        return ""

    text = re.sub(r'<div class="ql-editor[^"]*"[^>]*>', "", html_content)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li[^>]*>", "• ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)

    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class PostService:
    MAX_RETRIES = 3

    @staticmethod
    def publish_post(post_name: str) -> Dict[str, Any]:
        post = frappe.get_doc("Social Post", post_name)

        if post.status not in ["Draft", "Scheduled", "Failed", "Cancelled", "Publishing"]:
            return {"success": False, "error": f"Cannot publish from status '{post.status}'"}

        # Move to publishing
        if post.status != "Publishing":
            post.db_set("status", "Publishing")
            frappe.db.commit()

        try:
            if not post.platform or not post.account:
                raise Exception("Platform or Account missing")

            result = PostService._publish_to_platform(post, post.platform, post.account)

            # 🔥 SAFETY CHECK (fixes your crash)
            if not isinstance(result, PublishResult):
                raise Exception("Provider returned invalid response")

            if result.success:
                post.db_set({"status": "Published", "error_log": None})
            else:
                post.db_set({"status": "Failed", "error_log": result.error_message})

            frappe.db.commit()

            return {
                "success": result.success,
                "status": post.status,
                "results": {
                    post.platform: {
                        "success": result.success,
                        "post_id": result.post_id,
                        "post_url": result.post_url,
                        "error": result.error_message,
                    }
                },
            }

        except Exception as e:
            post.db_set({"status": "Failed", "error_log": str(e)})
            frappe.db.commit()

            frappe.log_error(
                title=f"Social Post Publish Error: {post_name}",
                message=str(e),
            )

            return {
                "success": False,
                "status": "Failed",
                "error": str(e),
            }

    @staticmethod
    def _publish_to_platform(post, platform, account):
        provider = get_provider(platform)(account)
        media_files = [row.file for row in post.media] if post.media else []

        plain_content = strip_html(post.content)

        result = provider.publish_post(
            content=plain_content,
            media_files=media_files,
            is_post=post.is_post,
            is_story=post.is_story,
            is_reel=post.is_reel,
            link=post.link,
            cta=post.cta,
        )

        if result.success and result.post_id:
            post.db_set(
                {
                    "post_id": result.post_id,
                    "status": "Published",
                    "error_log": None,
                }
            )
        else:
            post.db_set({"status": "Failed", "error_log": result.error_message or "Unknown error"})

        return result

    @staticmethod
    def _publish_instagram_content(provider, post, plain_content: str, media_files: list) -> PublishResult:
        """
        Handle Instagram-specific content types (Stories, Reels, Posts)
        """
        # Get Instagram-specific flags
        is_ig_story = getattr(post, "is_ig_story", False)
        is_ig_reel = getattr(post, "is_ig_reel", False)
        is_ig_post = getattr(post, "is_ig_post", True)  # Default to post

        # Validation: Only one content type should be selected
        selected_types = sum([is_ig_story, is_ig_reel, is_ig_post])

        if selected_types == 0:
            # Default to post if nothing selected
            is_ig_post = True
        elif selected_types > 1:
            return PublishResult(
                success=False,
                error_message="Please select only one Instagram content type (Story, Reel, or Post)",
            )

        # Content type specific validations
        if is_ig_story:
            if not media_files or len(media_files) == 0:
                return PublishResult(
                    success=False, error_message="Instagram Stories require at least one media file"
                )
            if len(media_files) > 1:
                return PublishResult(
                    success=False, error_message="Instagram Stories support only one media file at a time"
                )

        elif is_ig_reel:
            if not media_files or len(media_files) == 0:
                return PublishResult(success=False, error_message="Instagram Reels require a video file")
            if len(media_files) > 1:
                return PublishResult(
                    success=False, error_message="Instagram Reels support only one video at a time"
                )

            # Check if it's a video
            file_url = media_files[0].file_url if hasattr(media_files[0], "file_url") else media_files[0]
            if not file_url.lower().endswith((".mp4", ".mov")):
                return PublishResult(
                    success=False, error_message="Instagram Reels require video files (.mp4 or .mov)"
                )

        elif is_ig_post:
            if not media_files or len(media_files) == 0:
                return PublishResult(
                    success=False, error_message="Instagram Posts require at least one media file"
                )

        # Publish with appropriate content type
        return provider.publish_post(
            content=plain_content,
            media_files=media_files,
            is_story=is_ig_story,
            is_reel=is_ig_reel,
            is_post=is_ig_post,
        )

    @staticmethod
    def cancel_scheduled_post(post_name: str) -> Dict[str, Any]:
        post = frappe.get_doc("Social Post", post_name)

        if post.status not in ["Draft", "Scheduled", "Failed"]:
            return {"success": False, "message": f"Cannot cancel post from status '{post.status}'"}

        post.db_set("status", "Cancelled")
        frappe.db.commit()

        return {"success": True}
