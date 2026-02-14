import mimetypes, os , subprocess, shutil, json, frappe
from frappe import _
from pathlib import Path


def normalize_file_type(file_url: str, current_type: str | None = None) -> str | None:
    """
    Ensures valid MIME type like image/jpeg or video/mp4
    """
    if current_type and "/" in current_type:
        return current_type.lower()


    guess, _ = mimetypes.guess_type(file_url)
    if guess:
        return guess.lower()


    ext = file_url.split(".")[-1].lower()
    return {
        "jpg": "image/jpg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "mp4": "video/mp4",
        "mov": "video/mp4",
    }.get(ext)


def is_video(file_path: str) -> bool:
    """Check if file is a video"""
    return file_path.lower().endswith((".mp4", ".mov"))



def is_image(file_path: str) -> bool:
    """Check if file is an image"""
    return file_path.lower().endswith((".jpg", ".jpeg", ".png", ".gif"))



def get_full_path(file_path: str) -> str:
    """Get absolute local file path from Frappe file URL"""
    if not file_path:
        raise ValueError("Empty file path")
   
    file_path = file_path.strip()
    
    if "://" in file_path:
        from urllib.parse import urlparse
        parsed = urlparse(file_path)
        file_path = parsed.path
   
    # Handle Frappe's file path conventions
    mappings = (
        ("/private/files/", ("private", "files")),
        ("/public/files/", ("public", "files")),
        ("/files/", ("public", "files")),
    )
    
    for prefix, site_path in mappings:
        if file_path.startswith(prefix):
            relative = file_path[len(prefix):]
            return frappe.get_site_path(*site_path, relative)
   
    return frappe.get_site_path(file_path.lstrip("/"))


def get_video_duration(path: str) -> float:
    """Return video duration in seconds using ffprobe"""
    if not os.path.exists(path):
        frappe.throw(_("File not found: {0}").format(path))
   
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            path,
        ]
       
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30
        )
        data = json.loads(result.stdout)
        duration = float(data.get("format", {}).get("duration", 0))
       
        if duration <= 0:
            frappe.throw(_("Could not determine video duration"))
       
        return duration
   
    except subprocess.TimeoutExpired:
        frappe.throw(_("Video duration check timed out for: {0}").format(path))
    except FileNotFoundError:
        frappe.throw(
            _("FFmpeg not installed. Please contact your administrator to install FFmpeg")
        )
    except Exception as e:
        frappe.log_error(
            f"Error getting video duration: {str(e)}",
            "Video Duration Error"
        )
        frappe.throw(_("Error reading video duration: {0}").format(str(e)))


def get_video_dimensions(path: str) -> tuple:
    """Return (width, height) of the video using ffprobe"""
    if not os.path.exists(path):
        frappe.throw(_("Video file not found: {0}").format(path))
   
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "json",
            path,
        ]
       
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30
        )
       
        if result.returncode != 0:
            frappe.throw(_("Failed to read video dimensions: {0}").format(result.stderr))
       
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
       
        if not streams:
            frappe.throw(_("No video stream found in file"))
       
        stream = streams[0]
        width = stream.get("width")
        height = stream.get("height")
       
        if not width or not height:
            frappe.throw(_("Could not determine video dimensions"))
       
        return int(width), int(height)
   
    except subprocess.TimeoutExpired:
        frappe.throw(_("Video dimension check timed out for: {0}").format(path))
    except FileNotFoundError:
        frappe.throw(_("FFmpeg not installed. Please contact your administrator."))
    except Exception as e:
        frappe.log_error(
            f"Error getting video dimensions: {str(e)}",
            "Video Dimensions Error"
        )
        frappe.throw(_("Error reading video dimensions: {0}").format(str(e)))
        
# ===================================== Instgram ===============================================
def copy_to_public_temp(private_file_path: str, temp_files_list: list) -> str:
    """
    Copy private file to public directory temporarily
    
    Args:
        private_file_path: Path to the private file
        temp_files_list: List to track temp files for cleanup
        
    Returns:
        Public URL of the copied file
    """
    try:
        full_private_path = get_full_path(private_file_path)
        
        if not os.path.exists(full_private_path):
            frappe.throw(f"File not found: {private_file_path}")
        
        # Generate unique filename
        filename = Path(private_file_path).name
        timestamp = frappe.utils.now_datetime().strftime("%Y%m%d_%H%M%S_%f")
        unique_filename = f"ig_temp_{timestamp}_{filename}"
        
        # Public files directory
        public_files_dir = frappe.get_site_path("public", "files")
        os.makedirs(public_files_dir, exist_ok=True)
        
        public_file_path = os.path.join(public_files_dir, unique_filename)
        
        # Copy file
        shutil.copy2(full_private_path, public_file_path)
        
        # Generate public URL
        public_url = frappe.utils.get_url(f"/files/{unique_filename}")
        
        # Track for cleanup
        temp_files_list.append(public_file_path)
        
        frappe.logger().info(f"Copied private file to public temp: {public_url}")
        return public_url
        
    except Exception as e:
        frappe.log_error(f"Error copying to public: {str(e)}", "Instagram File Access")
        frappe.throw(f"Could not make file accessible: {str(e)}")


def cleanup_temp_files(temp_files_list: list):
    """
    Clean up temporary public files
    
    Args:
        temp_files_list: List of temporary file paths to delete
    """
    if temp_files_list:
        for temp_file in temp_files_list:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    frappe.logger().info(f"Cleaned up temp file: {temp_file}")
            except Exception as e:
                frappe.logger().warning(f"Could not delete {temp_file}: {str(e)}")
        
        # Clear the list after cleanup
        temp_files_list.clear()


def get_public_url(file_path: str, temp_files_list: list) -> str:
    """
    Get publicly accessible URL for Instagram API
    
    Args:
        file_path: File path or URL
        temp_files_list: List to track temp files for cleanup
        
    Returns:
        Public URL that Instagram API can access
    """
    if not file_path:
        frappe.throw("Empty file path provided")
    
    # Already a URL
    if file_path.startswith("http"):
        return file_path
    
    # Check if file is in private directory
    if "/private/files/" in file_path:
        return copy_to_public_temp(file_path, temp_files_list)
    
    # Public files can be accessed directly
    return frappe.utils.get_url(file_path)