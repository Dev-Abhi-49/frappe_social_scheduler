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
    """Strip HTML tags and convert to plain text"""
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
        """Main method to publish a post"""
        post = frappe.get_doc("Social Post", post_name)

        if post.status not in ["Draft", "Scheduled", "Failed", "Cancelled", "Publishing"]:
            return {"success": False, "error": f"Cannot publish from status '{post.status}'"}

        # Move to publishing state
        if post.status != "Publishing":
            post.db_set("status", "Publishing")
            frappe.db.commit()

        try:
            # Validate required fields
            if not post.platform or not post.account:
                raise Exception("Platform or Account missing")

            # Publish to platform
            result = PostService._publish_to_platform(post, post.platform, post.account)

            # Safety check: ensure result is PublishResult
            if not isinstance(result, PublishResult):
                raise Exception("Provider returned invalid response")

            # Update post status based on result
            if result.success:
                post.db_set({
                    "status": "Published",
                    "post_id": result.post_id,
                    "post_url": result.post_url,
                    "error_log": None,
                    "published_at": now_datetime()
                })
            else:
                post.db_set({
                    "status": "Failed",
                    "error_log": result.error_message
                })

            frappe.db.commit()

            return {
                "success": result.success,
                "status": post.status,
                "post_id": result.post_id,
                "post_url": result.post_url,
                "error": result.error_message,
            }

        except Exception as e:
            error_msg = str(e)
            post.db_set({
                "status": "Failed",
                "error_log": error_msg
            })
            frappe.db.commit()

            frappe.log_error(
                title=f"Social Post Publish Error: {post_name}",
                message=f"{error_msg}\n\n{frappe.get_traceback()}",
            )

            return {
                "success": False,
                "status": "Failed",
                "error": error_msg,
            }

    @staticmethod
    def _publish_to_platform(post, platform: str, account: str) -> PublishResult:
        """Publish to specific platform with proper provider"""
        try:
            # Get provider instance
            provider = get_provider(platform)(account)
            
            # Get media files
            media_files = [row.file for row in post.media] if post.media else []
            
            # Convert HTML content to plain text
            plain_content = strip_html(post.content)

            # Route to platform-specific handler
            if platform == "Instagram":
                return PostService._publish_instagram_content(provider, post, plain_content, media_files)
            elif platform == "Facebook":
                return PostService._publish_facebook_content(provider, post, plain_content, media_files)
            else:
                # Generic publishing for other platforms
                return provider.publish_post(
                    content=plain_content,
                    media_files=media_files,
                )

        except Exception as e:
            frappe.log_error(
                title=f"{platform} Publish Error",
                message=f"Post: {post.name}\nError: {str(e)}\n{frappe.get_traceback()}"
            )
            return PublishResult(
                success=False,
                error_message=f"Failed to publish to {platform}: {str(e)}"
            )

    @staticmethod
    def _publish_instagram_content(provider, post, plain_content: str, media_files: list) -> PublishResult:
        """
        Handle Instagram-specific content types (Posts, Stories, Reels)
        """
        # Get Instagram-specific flags from post
        is_ig_story = getattr(post, "is_ig_story", False)
        is_ig_reel = getattr(post, "is_ig_reel", False)
        is_ig_post = getattr(post, "is_ig_post", False)

        # Validation: Only one content type should be selected
        selected_types = sum([is_ig_story, is_ig_reel, is_ig_post])

        if selected_types == 0:
            # Default to post if nothing selected
            is_ig_post = True
        elif selected_types > 1:
            return PublishResult(
                success=False,
                error_message="Please select only one Instagram content type (Post, Story, or Reel)",
            )

        # Content type specific validations
        if is_ig_story:
            if not media_files or len(media_files) == 0:
                return PublishResult(
                    success=False,
                    error_message="Instagram Stories require at least one media file"
                )
            if len(media_files) > 1:
                return PublishResult(
                    success=False,
                    error_message="Instagram Stories support only one media file at a time"
                )

        elif is_ig_reel:
            if not media_files or len(media_files) == 0:
                return PublishResult(
                    success=False,
                    error_message="Instagram Reels require a video file"
                )
            if len(media_files) > 1:
                return PublishResult(
                    success=False,
                    error_message="Instagram Reels support only one video at a time"
                )

            # Check if it's a video
            file_url = getattr(media_files[0], "file_url", media_files[0])
            if not file_url.lower().endswith((".mp4", ".mov")):
                return PublishResult(
                    success=False,
                    error_message="Instagram Reels require video files (.mp4 or .mov)"
                )

        elif is_ig_post:
            if not media_files or len(media_files) == 0:
                return PublishResult(
                    success=False,
                    error_message="Instagram Posts require at least one media file"
                )

        # Publish with appropriate Instagram content type
        return provider.publish_post(
            content=plain_content,
            media_files=media_files,
            is_ig_story=is_ig_story,
            is_ig_reel=is_ig_reel,
            is_ig_post=is_ig_post,
        )

    @staticmethod
    def _publish_facebook_content(provider, post, plain_content: str, media_files: list) -> PublishResult:
        """
        Handle Facebook-specific content types (Posts, Stories, Reels)
        """
        # Get Facebook-specific flags from post
        is_fb_story = getattr(post, "is_fb_story", False)
        is_fb_reel = getattr(post, "is_fb_reel", False)
        is_fb_post = getattr(post, "is_fb_post", False)

        # Validation: Only one content type should be selected
        selected_types = sum([is_fb_story, is_fb_reel, is_fb_post])

        if selected_types == 0:
            # Default to post if nothing selected
            is_fb_post = True
        elif selected_types > 1:
            return PublishResult(
                success=False,
                error_message="Please select only one Facebook content type (Post, Story, or Reel)",
            )

        # Content type specific validations
        if is_fb_story:
            if not media_files or len(media_files) == 0:
                return PublishResult(
                    success=False,
                    error_message="Facebook Stories require at least one media file"
                )

        elif is_fb_reel:
            if not media_files or len(media_files) == 0:
                return PublishResult(
                    success=False,
                    error_message="Facebook Reels require a video file"
                )

            # Check if it's a video
            file_url = getattr(media_files[0], "file_url", media_files[0])
            if not file_url.lower().endswith((".mp4", ".mov")):
                return PublishResult(
                    success=False,
                    error_message="Facebook Reels require video files (.mp4 or .mov)"
                )

        # Get additional Facebook-specific parameters
        link = getattr(post, "link", None)
        cta = getattr(post, "cta", None)

        # Publish with appropriate Facebook content type
        return provider.publish_post(
            content=plain_content,
            media_files=media_files,
            is_fb_story=is_fb_story,
            is_fb_reel=is_fb_reel,
            is_fb_post=is_fb_post,
            link=link,
            cta=cta,
        )

    @staticmethod
    def cancel_scheduled_post(post_name: str) -> Dict[str, Any]:
        """Cancel a scheduled post"""
        post = frappe.get_doc("Social Post", post_name)

        if post.status not in ["Draft", "Scheduled", "Failed"]:
            return {
                "success": False,
                "message": f"Cannot cancel post from status '{post.status}'"
            }

        post.db_set("status", "Cancelled")
        frappe.db.commit()

        return {"success": True, "message": "Post cancelled successfully"}
