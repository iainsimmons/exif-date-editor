#!/usr/bin/env python3
import os
import subprocess
import re
from datetime import datetime, timedelta
from pathlib import Path

def find_exiftool():
    """Find exiftool binary"""
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

def read_alldates(file_paths):
    """Read AllDates for files. Returns dict of path -> date string."""
    if not file_paths:
        return {}
    result = {}
    try:
        cmd = [EXIFTOOL, "-s", "-s", "-s", "-AllDates"] + [str(p) for p in file_paths]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        output = proc.stdout.decode('utf-8', errors='replace')
        current_file = None
        for line in output.splitlines():
            line_stripped = line.strip()
            if not line_stripped:
                continue
            if line_stripped.startswith('========'):
                current_file = line_stripped.replace('========', '').strip()
                continue
            if line_stripped.lower().startswith('alldates') and current_file:
                parts = line_stripped.split(':', 1)
                if len(parts) == 2:
                    result[current_file] = parts[1].strip()
                    # Also store by basename
                    result[os.path.basename(current_file)] = parts[1].strip()
            elif current_file and ':' in line_stripped and not line_stripped.lower().startswith('alldates'):
                # Sometimes just the value
                if re.match(r'^\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$', line_stripped):
                    result[current_file] = line_stripped
                    result[os.path.basename(current_file)] = line_stripped
            elif not current_file and re.match(r'^\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$', line_stripped):
                # Single file case
                if file_paths:
                    result[str(file_paths[0])] = line_stripped
                    result[os.path.basename(str(file_paths[0]))] = line_stripped
    except Exception as e:
        print(f"Error reading dates: {e}")
    return result

def set_alldates(file_paths, date_str):
    """Set AllDates for files. date_str should be YYYY:MM:DD HH:MM:SS"""
    if not file_paths or not date_str:
        return False, "No files or date"
    if not re.match(r'^\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$', date_str):
        return False, "Invalid date format. Use YYYY:MM:DD HH:MM:SS"
    try:
        cmd = [EXIFTOOL, f'-AllDates={date_str}', '-overwrite_original'] + [str(p) for p in file_paths]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out = proc.stdout.decode('utf-8', errors='replace')
        err = proc.stderr.decode('utf-8', errors='replace')
        if proc.returncode != 0:
            return False, err or out
        return True, out
    except Exception as e:
        return False, str(e)

def parse_offset(offset_str):
    """Parse offset like -1d, +10h, -30m, +2d3h"""
    offset_str = offset_str.strip().lower()
    total_seconds = 0
    for sign, num, unit in re.findall(r'([+-]?)(\d+)([dhms])', offset_str):
        n = int(num)
        if sign == '-':
            n = -n
        elif sign == '+' and offset_str and not offset_str.startswith(('+','-')) and total_seconds == 0:
            pass
        if unit == 'd':
            total_seconds += n * 86400
        elif unit == 'h':
            total_seconds += n * 3600
        elif unit == 'm':
            total_seconds += n * 60
        elif unit == 's':
            total_seconds += n
    return timedelta(seconds=total_seconds)

def apply_offset(file_paths, offset_str):
    """Apply offset to each file's AllDates"""
    if not file_paths or not offset_str:
        return False, "No files or offset"
    td = parse_offset(offset_str)
    dates = read_alldates(file_paths)
    success = 0
    errors = []
    for f in file_paths:
        fstr = str(f)
        cur = dates.get(fstr) or dates.get(os.path.basename(fstr))
        if not cur:
            errors.append(f"{os.path.basename(fstr)}: no date found")
            continue
        try:
            dt = datetime.strptime(cur, "%Y:%m:%d %H:%M:%S")
            new_dt = dt + td
            new_str = new_dt.strftime("%Y:%m:%d %H:%M:%S")
            ok, msg = set_alldates([f], new_str)
            if ok:
                success += 1
            else:
                errors.append(f"{os.path.basename(fstr)}: {msg}")
        except Exception as e:
            errors.append(f"{os.path.basename(fstr)}: {e}")
    return success > 0, f"Updated {success}/{len(file_paths)} files. " + "; ".join(errors)

def set_date_keep_time(file_paths, new_date_str):
    """Set date keeping original time. new_date_str should be YYYY-MM-DD or YYYY:MM:DD"""
    if not file_paths or not new_date_str:
        return False, "No files or date"
    new_date_str = new_date_str.replace('-', ':')
    if not re.match(r'^\d{4}:\d{2}:\d{2}$', new_date_str):
        return False, "Invalid date format. Use YYYY-MM-DD"
    dates = read_alldates(file_paths)
    success = 0
    errors = []
    for f in file_paths:
        fstr = str(f)
        cur = dates.get(fstr) or dates.get(os.path.basename(fstr))
        if not cur:
            errors.append(f"{os.path.basename(fstr)}: no date found")
            continue
        try:
            parts = cur.split()
            time_part = parts[1] if len(parts) == 2 else "00:00:00"
            new_str = f"{new_date_str} {time_part}"
            ok, msg = set_alldates([f], new_str)
            if ok:
                success += 1
            else:
                errors.append(f"{os.path.basename(fstr)}: {msg}")
        except Exception as e:
            errors.append(f"{os.path.basename(fstr)}: {e}")
    return success > 0, f"Updated {success}/{len(file_paths)} files. " + "; ".join(errors)
