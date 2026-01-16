import os
import sys
import uuid
import json
import subprocess
from PIL import Image
from datetime import datetime

# Configuration
INPUT_DIR = '/app/input'
OUTPUT_DIR = '/app/output'
LOG_FILE = '/app/output/processing_log.json'
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024 # 2GB
MAX_IMAGE_PIXELS = 200 * 1000 * 1000 # 200MP

# Safety: Prevent decompression bombs
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

def log_event(event_type, message, file_info=None):
    valid_types = ["SYSTEM", "INFO", "SUCCESS", "ERROR", "SECURITY", "WARNING", "SKIP"]
    if event_type not in valid_types:
        event_type = "INFO"

    timestamp = datetime.now().isoformat()
    entry = {
        "timestamp": timestamp,
        "type": event_type,
        "message": message,
        "file": file_info
    }

    # Console Output (Human Readable)
    # Format: [HH:MM:SS] [TYPE] Message (Extra Info)
    time_str = datetime.now().strftime("%H:%M:%S")
    console_msg = f"[{time_str}] [{event_type}] {message}"
    
    if file_info:
        # Extract meaningful info for console to keep it clean
        if "file" in file_info:
             console_msg += f" : {file_info['file']}"
        elif "input" in file_info and "output" in file_info:
             console_msg += f" : {os.path.basename(file_info['input'])} -> {os.path.basename(file_info['output'])}"
        elif "mime" in file_info:
             console_msg += f" ({file_info.get('mime', 'Unknown')})"

    print(console_msg)

    # Append to log file
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception as e:
        print(f"FATAL: Could not write to log file: {e}")

def get_mime_type(filepath):
    try:
        mime = magic.Magic(mime=True)
        return mime.from_file(filepath)
    except Exception as e:
        log_event("ERROR", f"Failed to detect MIME type: {e}")
        return None

def sanitize_image(input_path, output_path):
    try:
        # Open the image
        with Image.open(input_path) as img:
            # Handle format-specific logic
            output_format = img.format if img.format else 'PNG'
            
            # Reconstruction Strategy:
            # We create a new image (=new container) and copy PIXELS only.
            # This implicitly drops Exif, ICC profiles, and unknown chunks.
            
            # Force full data read
            data = img.getdata()
            clean_img = Image.new(img.mode, img.size)
            clean_img.putdata(data)
            
            # Determine output extension based on format
            # Using the original (safe) format is better for size/quality
            if output_format == 'JPEG':
                # exif=b"" ensures we don't accidentally copy any info (though clean_img shouldn't have any)
                clean_img.save(output_path, format='JPEG', quality=90, optimize=True, exif=b"")
            elif output_format == 'GIF':
                 # Static GIF (First frame only) - Animations should go to sanitize_gif via FFmpeg
                 clean_img.save(output_path, format='GIF', save_all=False, exif=b"")
            else:
                clean_img.save(output_path, format=output_format, exif=b"")
                
            log_event("SUCCESS", "Image sanitized successfully", {"input": input_path, "output": output_path})
            return True
    except Exception as e:
        log_event("ERROR", f"Image sanitization failed: {e}", {"file": input_path})
        return False

def sanitize_video(input_path, output_path):
    try:
        # L3 Defense: Full Transcode with Explicit Stream Mapping
        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-map', '0:v:0',       # Pick first video stream
            '-map', '0:a:0?',      # Pick first audio stream (optional if exists)
            '-map_metadata', '-1', # Strip global metadata
            '-map_chapters', '-1', # Strip chapters
            '-c:v', 'libx264',     # Re-encode Video
            '-preset', 'fast',
            '-c:a', 'aac',         # Re-encode Audio
            output_path
        ]
        
        # Run subprocess
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        
        if result.returncode == 0:
            log_event("SUCCESS", "Video sanitized successfully", {"input": input_path, "output": output_path})
            return True
        else:
            log_event("ERROR", f"Video sanitization failed: {result.stderr.decode()}", {"file": input_path})
            return False

    except subprocess.TimeoutExpired:
        log_event("SECURITY", "Video processing timed out (Possible DoS)", {"file": input_path})
        return False
    except Exception as e:
        log_event("ERROR", f"Video unexpected error: {e}", {"file": input_path})
        return False

def sanitize_gif(input_path, output_path):
    try:
        # Use ffmpeg to process GIF as video
        cmd = [
            'ffmpeg', '-y',
            '-i', input_path,
            '-map', '0:v:0',       # Pick video (GIF is valid video stream)
            '-map_metadata', '-1',
            output_path
        ]
        
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        
        if result.returncode == 0:
            log_event("SUCCESS", "GIF sanitized successfully (Animation preserved)", {"input": input_path, "output": output_path})
            return True
        else:
            log_event("ERROR", f"GIF sanitization failed: {result.stderr.decode()}", {"file": input_path})
            return False

    except subprocess.TimeoutExpired:
        log_event("SECURITY", "GIF processing timed out", {"file": input_path})
        return False
    except Exception as e:
        log_event("ERROR", f"GIF unexpected error: {e}", {"file": input_path})
        return False

def process_file(filename):
    input_path = os.path.join(INPUT_DIR, filename)
    
    # Ignore hidden files or directories
    if filename.startswith('.') or os.path.isdir(input_path):
        return

    log_event("INFO", "Processing file", {"file": filename})
    
    # 1. Resource Check (File Size)
    file_size = os.path.getsize(input_path)
    if file_size > MAX_FILE_SIZE_BYTES:
        log_event("SECURITY", f"File size exceeds limit ({file_size} bytes)", {"file": filename})
        return

    # 2. Diagnosis / Type Check
    mime_type = get_mime_type(input_path)
    log_event("INFO", f"Detected MIME type: {mime_type}", {"file": filename})
    
    if not mime_type:
        log_event("ERROR", "Could not detect MIME type", {"file": filename})
        return

    # 3. Sanitize based on type
    # Generate safe output filename (UUID)
    safe_name = str(uuid.uuid4())
    
    is_video = mime_type.startswith('video/')
    is_image = mime_type.startswith('image/')
    
    try:
        if mime_type == 'image/gif':
             output_filename = f"{safe_name}.gif"
             output_path = os.path.join(OUTPUT_DIR, output_filename)
             sanitize_gif(input_path, output_path)
        
        elif is_video:
            output_filename = f"{safe_name}.mp4"
            output_path = os.path.join(OUTPUT_DIR, output_filename)
            sanitize_video(input_path, output_path)
            
        elif is_image:
            # Determine extension from MIME or original
            # For PoC, let's keep original extension to avoid confusion, provided it's safe
            ext = os.path.splitext(filename)[1].lower()
            if not ext in ['.jpg', '.jpeg', '.png', '.webp', '.bmp']:
                 ext = '.png' # Fallback
            
            output_filename = f"{safe_name}{ext}"
            output_path = os.path.join(OUTPUT_DIR, output_filename)
            sanitize_image(input_path, output_path)
            
        else:
            log_event("WARNING", "Unsupported file type, skipping", {"file": filename, "mime": mime_type})
    except Image.DecompressionBombError:
        log_event("SECURITY", "Decompression bomb detected (Image too large)", {"file": filename})
    except Exception as e:
        log_event("ERROR", f"Unhandled exception during processing: {e}", {"file": filename})

def main():
    log_event("SYSTEM", "Sanitizer started")
    
    # Check if input dir exists
    if not os.path.exists(INPUT_DIR):
        log_event("ERROR", "Input directory not found")
        return

    # Iterate over files in input
    try:
        files = os.listdir(INPUT_DIR)
        if not files:
            log_event("INFO", "No files found in input directory")
            
        for filename in files:
            process_file(filename)
    except Exception as e:
        log_event("ERROR", f"Main loop failed: {e}")

    log_event("SYSTEM", "Sanitization complete")

if __name__ == "__main__":
    main()
