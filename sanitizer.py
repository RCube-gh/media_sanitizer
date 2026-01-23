import os
import sys
import uuid
import json
import subprocess
import magic
import re
import time
from tqdm import tqdm
from PIL import Image
from datetime import datetime
import queue
import concurrent.futures

# Configuration
INPUT_DIR = '/app/input'
OUTPUT_DIR = '/app/output'
LOG_FILE = '/app/output/processing_log.json'
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024 # 2GB
MAX_IMAGE_PIXELS = 200 * 1000 * 1000 # 200MP
MAX_WORKERS = 2

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

    # Use tqdm.write to avoid interfering with progress bars
    tqdm.write(console_msg)

    # Append to log file
    try:
        with open(LOG_FILE, 'a') as f:
            f.write(json.dumps(entry) + '\n')
    except Exception as e:
        # tqdm.write(f"FATAL: Could not write to log file: {e}")
        pass

def get_mime_type(filepath):
    try:
        mime = magic.Magic(mime=True)
        return mime.from_file(filepath)
    except Exception as e:
        log_event("ERROR", f"Failed to detect MIME type: {e}")
        return None

def get_video_duration(input_path):
    cmd = [
        'ffprobe', 
        '-v', 'error', 
        '-show_entries', 'format=duration', 
        '-of', 'default=noprint_wrappers=1:nokey=1', 
        input_path
    ]
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        return float(result.stdout.strip())
    except (ValueError, subprocess.SubprocessError):
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

def sanitize_video(input_path, output_path, pbar_pos=0):
    try:
        cmd = [
            'ffmpeg', '-y', '-nostdin',
            '-i', input_path,
            '-map', '0:v:0',
            '-map', '0:a:0?',
            '-map_metadata', '-1',
            '-map_chapters', '-1',
            '-c:v', 'libx264',
            '-preset', 'medium',
            '-crf', '23',
            '-c:a', 'aac',
            output_path
        ]
        
        duration = get_video_duration(input_path)
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, encoding='utf-8')
        
        filename = os.path.basename(input_path)
        pbar = None
        if duration:
            pbar = tqdm(total=duration, unit="s", desc=f"Video ({filename[:10]}...)", ncols=80, leave=True, position=pbar_pos)
        else:
            pbar = tqdm(unit="s", desc=f"Video ({filename[:10]}...)", ncols=80, leave=True, position=pbar_pos)

        start_time = time.time()
        time_pattern = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
        
        if duration:
            # Allow for slow processing (up to 5x real-time in worst case, or at least 1 hour)
            timeout_limit = max(3600, duration * 5)
        else:
            timeout_limit = 3600 # Default 1 hour if duration unknown

        while True:
            # Check timeout
            if time.time() - start_time > timeout_limit:
                process.kill()
                if pbar: pbar.close()
                log_event("SECURITY", f"Video processing timed out ({timeout_limit}s limit) - Cleaning up", {"file": input_path})
                if os.path.exists(output_path):
                    try: os.remove(output_path)
                    except: pass
                return False

            line = process.stderr.readline()
            if not line and process.poll() is not None:
                break
            
            if line:
                match = time_pattern.search(line)
                if match and pbar and duration:
                    h, m, s = match.groups()
                    current_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                    pbar.n = min(current_seconds, duration)
                    pbar.refresh()

        if pbar: pbar.close()
        
        if process.returncode == 0:
            log_event("SUCCESS", "Video sanitized successfully", {"input": input_path, "output": output_path})
            return True
        else:
            # Consume remaining stderr if any
            err_output = process.stderr.read()
            log_event("ERROR", f"Video sanitization failed: {err_output}", {"file": input_path})
            return False

    except Exception as e:
        log_event("ERROR", f"Video unexpected error: {e}", {"file": input_path})
        return False

def sanitize_audio(input_path, output_path, pbar_pos=0):
    try:
        cmd = [
            'ffmpeg', '-y', '-nostdin',
            '-i', input_path,
            '-map', '0:a:0',       # Pick first audio stream
            '-map_metadata', '-1', # Strip metadata
            '-c:a', 'aac',         # Re-encode Audio to AAC
            '-b:a', '192k',        # Good quality bitrate
            output_path
        ]
        
        duration = get_video_duration(input_path)
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, encoding='utf-8')
        
        filename = os.path.basename(input_path)
        pbar = None
        if duration:
            pbar = tqdm(total=duration, unit="s", desc=f"Audio ({filename[:10]}...)", ncols=80, leave=True, position=pbar_pos)
        else:
            pbar = tqdm(unit="s", desc=f"Audio ({filename[:10]}...)", ncols=80, leave=True, position=pbar_pos)

        start_time = time.time()
        time_pattern = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
        
        if duration:
            timeout_limit = max(3600, duration * 5)
        else:
            timeout_limit = 3600

        while True:
            # Check timeout
            if time.time() - start_time > timeout_limit:
                process.kill()
                if pbar: pbar.close()
                log_event("SECURITY", f"Audio processing timed out ({timeout_limit}s limit) - Cleaning up", {"file": input_path})
                if os.path.exists(output_path):
                    try: os.remove(output_path)
                    except: pass
                return False

            line = process.stderr.readline()
            if not line and process.poll() is not None:
                break
            
            if line:
                match = time_pattern.search(line)
                if match and pbar and duration:
                    h, m, s = match.groups()
                    current_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                    pbar.n = min(current_seconds, duration)
                    pbar.refresh()

        if pbar: pbar.close()
        
        if process.returncode == 0:
            log_event("SUCCESS", "Audio sanitized successfully", {"input": input_path, "output": output_path})
            return True
        else:
            err_output = process.stderr.read()
            log_event("ERROR", f"Audio sanitization failed: {err_output}", {"file": input_path})
            return False

    except Exception as e:
        log_event("ERROR", f"Audio unexpected error: {e}", {"file": input_path})
        return False

def sanitize_gif(input_path, output_path, pbar_pos=0):
    try:
        cmd = [
            'ffmpeg', '-y', '-nostdin',
            '-i', input_path,
            '-map', '0:v:0',
            '-map_metadata', '-1',
            '-f', 'gif',
            output_path
        ]
        
        # GIFs can be treated as videos
        duration = get_video_duration(input_path)
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, encoding='utf-8')
        
        filename = os.path.basename(input_path)
        pbar = None
        if duration:
            pbar = tqdm(total=duration, unit="s", desc=f"GIF ({filename[:10]}...)", ncols=80, leave=True, position=pbar_pos)
        else:
            pbar = tqdm(unit="s", desc=f"GIF ({filename[:10]}...)", ncols=80, leave=True, position=pbar_pos)

        start_time = time.time()
        time_pattern = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
        
        while True:
             if time.time() - start_time > 300:
                process.kill()
                if pbar: pbar.close()
                log_event("SECURITY", "GIF processing timed out - Cleaning up", {"file": input_path})
                if os.path.exists(output_path):
                    try: os.remove(output_path)
                    except: pass
                return False

             line = process.stderr.readline()
             if not line and process.poll() is not None:
                break
            
             if line:
                match = time_pattern.search(line)
                if match and pbar and duration:
                    h, m, s = match.groups()
                    current_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                    pbar.n = min(current_seconds, duration)
                    pbar.refresh()
        
        if pbar: pbar.close()

        if process.returncode == 0:
            log_event("SUCCESS", "GIF sanitized successfully", {"input": input_path, "output": output_path})
            return True
        else:
             log_event("ERROR", f"GIF sanitization failed", {"file": input_path})
             return False

    except Exception as e:
        log_event("ERROR", f"GIF unexpected error: {e}", {"file": input_path})
        return False

def process_file(rel_path, pbar_pos=0):
    input_path = os.path.join(INPUT_DIR, rel_path)
    
    # Safety check (though main filter already does this)
    if os.path.isdir(input_path):
        return

    log_event("INFO", "Processing file", {"file": rel_path})
    
    # 1. Resource Check (File Size)
    file_size = os.path.getsize(input_path)
    if file_size > MAX_FILE_SIZE_BYTES:
        log_event("SECURITY", f"File size exceeds limit ({file_size} bytes)", {"file": rel_path})
        return

    # 2. Diagnosis / Type Check
    mime_type = get_mime_type(input_path)
    if not mime_type:
        log_event("ERROR", "Could not detect MIME type", {"file": rel_path})
        return

    # 3. Prepare Output Path
    # Maintain directory structure
    rel_dir = os.path.dirname(rel_path)
    base_name = os.path.basename(rel_path)
    
    # Sanitize the filename part (preserving safety)
    safe_base = re.sub(r'[^a-zA-Z0-9._-]', '_', os.path.splitext(base_name)[0])
    if not safe_base:
        safe_base = "sanitized_" + str(uuid.uuid4())[:8]
    
    target_dir = os.path.join(OUTPUT_DIR, rel_dir)
    os.makedirs(target_dir, exist_ok=True)
    
    is_video = mime_type.startswith('video/')
    is_image = mime_type.startswith('image/')
    is_audio = mime_type.startswith('audio/')
    
    try:
        if mime_type == 'image/gif':
             output_path = os.path.join(target_dir, f"{safe_base}.gif")
             sanitize_gif(input_path, output_path, pbar_pos)
        
        elif is_video:
            output_path = os.path.join(target_dir, f"{safe_base}.mp4")
            sanitize_video(input_path, output_path, pbar_pos)
            
        elif is_image:
            ext = os.path.splitext(base_name)[1].lower()
            if not ext in ['.jpg', '.jpeg', '.png', '.webp', '.bmp']:
                 ext = '.png'
            
            output_path = os.path.join(target_dir, f"{safe_base}{ext}")
            sanitize_image(input_path, output_path)

        elif is_audio:
            output_path = os.path.join(target_dir, f"{safe_base}.m4a")
            sanitize_audio(input_path, output_path, pbar_pos)
            
        else:
            log_event("WARNING", "Unsupported file type, skipping", {"file": rel_path, "mime": mime_type})
    except Image.DecompressionBombError:
        log_event("SECURITY", "Decompression bomb detected (Image too large)", {"file": rel_path})
    except Exception as e:
        log_event("ERROR", f"Unhandled exception during processing: {e}", {"file": rel_path})

def main():
    log_event("SYSTEM", f"Sanitizer started (Max Workers: {MAX_WORKERS})")
    
    # Check if input dir exists
    if not os.path.exists(INPUT_DIR):
        log_event("ERROR", "Input directory not found")
        return

    # Iterate over files in input recursively
    task_files = []
    try:
        for root, dirs, files in os.walk(INPUT_DIR):
            for f in files:
                if not f.startswith('.'):
                    # Calculate path relative to INPUT_DIR
                    rel_path = os.path.relpath(os.path.join(root, f), INPUT_DIR)
                    task_files.append(rel_path)
        
        if not task_files:
            log_event("INFO", "No files found in input directory")
            return
        
        # Sort files to process them in a predictable order
        task_files.sort()

        # Worker Slot Queue [0, 1, ... MAX_WORKERS-1]
        slot_queue = queue.Queue()
        for i in range(MAX_WORKERS):
            slot_queue.put(i)

        def worker_wrapper(rel_path):
             slot = slot_queue.get()
             try:
                 process_file(rel_path, pbar_pos=slot)
             finally:
                 slot_queue.put(slot)

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            executor.map(worker_wrapper, task_files)

    except Exception as e:
        log_event("ERROR", f"Main loop failed: {e}")

    log_event("SYSTEM", "Sanitization complete")

if __name__ == "__main__":
    main()
