#!/usr/bin/env python3
import os
import subprocess
import tempfile
from pathlib import Path

def find_exiftool():
    script_dir = Path(__file__).parent
    candidates = [
        script_dir / "exiftool-bin" / "exiftool",
        script_dir / "exiftool",
    ]
    for c in candidates:
        p = Path(c)
        if p.exists() and os.access(p, os.X_OK):
            return str(p.resolve())
    return "exiftool"

EXIFTOOL = find_exiftool()

def get_preview_image(file_path):
    """Get a displayable preview image path for JPG/ORF"""
    file_path = str(file_path)
    ext = Path(file_path).suffix.lower()
    
    if ext in ['.jpg', '.jpeg']:
        return file_path
    
    if ext in ['.orf']:
        # Try to extract preview
        try:
            # Try PreviewImage first
            cmd = [EXIFTOOL, '-b', '-PreviewImage', file_path]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode == 0 and len(proc.stdout) > 1000:
                fd, tmp_path = tempfile.mkstemp(suffix='.jpg', prefix='exifdate_preview_')
                os.write(fd, proc.stdout)
                os.close(fd)
                return tmp_path
            # Try JpgFromRaw
            cmd = [EXIFTOOL, '-b', '-JpgFromRaw', file_path]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if proc.returncode == 0 and len(proc.stdout) > 1000:
                fd, tmp_path = tempfile.mkstemp(suffix='.jpg', prefix='exifdate_preview_')
                os.write(fd, proc.stdout)
                os.close(fd)
                return tmp_path
        except Exception as e:
            print(f"Error extracting preview: {e}")
    
    return None
