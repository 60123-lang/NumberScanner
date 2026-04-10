import base64
import requests
import json
import re
import os
from datetime import datetime


def _normalize_header_key(raw_key):
    key = str(raw_key or "").strip().lower()
    key = key.replace(" ", "")
    key = key.replace(".", "")
    key = key.replace("_", "")

    aliases = {
        "s": "S",
        "sn": "S",
        "sno": "S",
        "serial": "S",
        "serialno": "S",
        "serialnumber": "S",
        "row": "S",
        "n1": "N1",
        "f1": "F1",
        "s1": "S1",
        "d1": "D1",
        "demand1": "D1",
        "n2": "N2",
        "f2": "F2",
        "s2": "S2",
        "d2": "D2",
        "demand2": "D2",
        "n3": "N3",
        "f3": "F3",
        "s3": "S3",
    }
    return aliases.get(key)


def _clean_cell_value(raw):
    if raw is None:
        return None
    v = str(raw).strip()
    if v == "":
        return None

    lower_v = v.lower()
    if lower_v in {"null", "none", "nil", "na", "n/a", "[?]", "?", "-"}:
        return None

    # Ditto/arrow placeholders should be treated as continuation markers.
    if v in {"↓", "⬇", "↧", "|", "||", '"', "''", "``", "”", "′", "ˮ"}:
        return None

    # Handle simple numeric strings (including leading zeros)
    if re.fullmatch(r"\d+", v):
        return v

    # Keep non-numeric text untouched so downstream cleaning can decide.
    return v


def _parse_markdown_table(output):
    lines = [line.strip() for line in str(output).splitlines() if "|" in line]
    if len(lines) < 2:
        return None

    header_line = lines[0]
    headers = [h.strip() for h in header_line.strip("|").split("|")]

    normalized_headers = []
    active_group = None
    for h in headers:
        token = str(h or "").strip().lower()
        token = token.replace(" ", "")
        token = token.replace(".", "")
        token = token.replace("_", "")

        mapped = None
        if token in {"sn", "sno", "serial", "serialno", "serialnumber", "row"}:
            mapped = "S"
        elif token in {"n1", "n2", "n3"}:
            active_group = token[-1]
            mapped = f"N{active_group}"
        elif token in {"f1", "f2", "f3"}:
            active_group = token[-1]
            mapped = f"F{active_group}"
        elif token in {"s1", "s2", "s3"}:
            active_group = token[-1]
            mapped = f"S{active_group}"
        elif token == "f" and active_group:
            mapped = f"F{active_group}"
        elif token == "s" and active_group:
            mapped = f"S{active_group}"
        else:
            mapped = _normalize_header_key(h)

        normalized_headers.append(mapped)

    if not any(h in {"N1", "N2", "N3"} for h in normalized_headers):
        return None

    data = []
    for line in lines[1:]:
        # Skip separator line like |---|---|
        no_pipe = line.replace("|", "").replace("-", "").replace(":", "").strip()
        if no_pipe == "":
            continue

        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue

        row = {}
        for i, cell in enumerate(cells):
            if i >= len(normalized_headers):
                continue
            key = normalized_headers[i]
            if not key:
                continue
            row[key] = _clean_cell_value(cell)

        if row:
            data.append(row)

    return data if data else None


def _extract_data_rows(output):
    # 1) Direct JSON payload
    try:
        parsed = json.loads(output)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass

    # 2) JSON inside markdown code fence
    fence_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", output, re.DOTALL | re.IGNORECASE)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1))
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass

    # 3) Any JSON array within output
    json_match = re.search(r"\[.*\]", output, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass

    # 4) Markdown table fallback
    table_rows = _parse_markdown_table(output)
    if table_rows:
        return table_rows

    return None

def clean_value(val):
    """
    Ensures only digits are returned. 
    Returns the integer if it's a digit string, else returns 0.
    """
    if val is None:
        return None
    
    # Convert to string and strip whitespace
    s_val = str(val).strip()
    
    # If it's a digit string, return it as an int
    if s_val.isdigit():
        return int(s_val)
    
    # Per your requirement: anything else (symbols like alpha, lines, etc.) equals 0
    return 0

def apply_continuation_logic(data):
    """
    Fills missing values (null/ditto markers) by carrying forward the last known digit.
    Proceeds per section (N1, N2, N3). If a section number is missing, its F/S values reset to 0.
    """
    def is_continuation_marker(val):
        if val is None:
            return False
        return str(val).strip() in {"↓", "⬇", "↧", "|", "||", '"', "''", "``", "”", "′", "ˮ"}

    # Initialize trackers for columns that commonly use vertical continuation lines.
    last_known = {
        "F1": 0,
        "S1": 0,
        "F2": 0,
        "S2": 0,
        "F3": 0,
        "S3": 0,
    }

    for row in data:
        # ---------------------------
        # LEFT SIDE (N1 -> F1, S1)
        # ---------------------------
        n1_val = row.get("N1")

        # Clean N1: Keep as string to preserve leading zeros if digits
        if n1_val is not None and str(n1_val).strip().isdigit():
            n1_val = str(n1_val).strip()
            row["N1"] = n1_val
        else:
            n1_val = None
            row["N1"] = None

        # Check if N1 is present (not None)
        if n1_val is not None:
            # Handle F1
            f1_raw = row.get("F1")
            if f1_raw is not None and not is_continuation_marker(f1_raw):
                cleaned = clean_value(f1_raw)
                row["F1"] = cleaned
                last_known["F1"] = cleaned
            else:
                row["F1"] = last_known["F1"]

            # Handle S1
            s1_raw = row.get("S1")
            if s1_raw is not None and not is_continuation_marker(s1_raw):
                cleaned = clean_value(s1_raw)
                row["S1"] = cleaned
                last_known["S1"] = cleaned
            else:
                row["S1"] = last_known["S1"]
        else:
            # N1 missing: force 0 and reset tracker
            row["F1"] = 0
            row["S1"] = 0
            last_known["F1"] = 0
            last_known["S1"] = 0

        # ---------------------------
        # RIGHT SIDE (N2 -> F2, S2)
        # ---------------------------
        n2_val = row.get("N2")

        # Clean N2: Keep as string to preserve leading zeros if digits
        if n2_val is not None and str(n2_val).strip().isdigit():
            n2_val = str(n2_val).strip()
            row["N2"] = n2_val
        else:
            n2_val = None
            row["N2"] = None

        # Check if N2 is present
        if n2_val is not None:
            # Handle F2
            f2_raw = row.get("F2")
            if f2_raw is not None and not is_continuation_marker(f2_raw):
                cleaned = clean_value(f2_raw)
                row["F2"] = cleaned
                last_known["F2"] = cleaned
            else:
                row["F2"] = last_known["F2"]

            # Handle S2
            s2_raw = row.get("S2")
            if s2_raw is not None and not is_continuation_marker(s2_raw):
                cleaned = clean_value(s2_raw)
                row["S2"] = cleaned
                last_known["S2"] = cleaned
            else:
                row["S2"] = last_known["S2"]
        else:
            # N2 missing: force 0 and reset tracker
            row["F2"] = 0
            row["S2"] = 0
            last_known["F2"] = 0
            last_known["S2"] = 0

        # ---------------------------
        # FAR RIGHT SECTION (N3 -> F3, S3)
        # ---------------------------
        n3_val = row.get("N3")

        # Clean N3: Keep as string to preserve leading zeros if digits
        if n3_val is not None and str(n3_val).strip().isdigit():
            n3_val = str(n3_val).strip()
            row["N3"] = n3_val
        else:
            n3_val = None
            row["N3"] = None

        # Check if N3 is present
        if n3_val is not None:
            # Handle F3
            f3_raw = row.get("F3")
            if f3_raw is not None and not is_continuation_marker(f3_raw):
                cleaned = clean_value(f3_raw)
                row["F3"] = cleaned
                last_known["F3"] = cleaned
            else:
                row["F3"] = last_known["F3"]

            # Handle S3
            s3_raw = row.get("S3")
            if s3_raw is not None and not is_continuation_marker(s3_raw):
                cleaned = clean_value(s3_raw)
                row["S3"] = cleaned
                last_known["S3"] = cleaned
            else:
                row["S3"] = last_known["S3"]
        else:
            # N3 missing: force 0 and reset tracker
            row["F3"] = 0
            row["S3"] = 0
            last_known["F3"] = 0
            last_known["S3"] = 0

    return data

def save_llm_output(raw_output, processed_data, image_name="document"):
    """
    Save both raw LLM output and processed data to JSON files.
    """
    json_output_dir = r"D:\Works\numbersscanner\numbersys\scanner\json_outputs"
    
    # Create folder if it doesn't exist
    if not os.path.exists(json_output_dir):
        os.makedirs(json_output_dir)
    
    # Create filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Save raw LLM response
    raw_filename = f"llm_raw_{image_name}_{timestamp}.json"
    raw_filepath = os.path.join(json_output_dir, raw_filename)
    with open(raw_filepath, "w") as f:
        json.dump({"raw_output": raw_output}, f, indent=2)
    
    # Save processed data
    processed_filename = f"llm_processed_{image_name}_{timestamp}.json"
    processed_filepath = os.path.join(json_output_dir, processed_filename)
    with open(processed_filepath, "w") as f:
        json.dump(processed_data, f, indent=2)
    
    return raw_filepath, processed_filepath

def extract_data_with_qwen(image_path, api_key):
    """
    Main extraction function that takes image path and API key.
    Returns processed data or None if extraction fails.
    """
    BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"

    try:
        # ✅ Step 1: Read image as base64
        with open(image_path, "rb") as img_file:
            image_bytes = img_file.read()
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")

        # ✅ Step 2: Concise Prompt
        prompt = '''
Role: You are a high-precision data extraction assistant. Your goal is to convert handwritten ledger sheets into a digital Markdown table with 100% accuracy.

Instructions:

Identify Column Headers: Detect all column headers (e.g., S.N, N.1, F, S, etc.). Create a Markdown table using these exact headers.

Handle Continuity Markers (Arrows/Ditto):

Protocol: Persistent Column Memory (The "Carry-Forward" Rule)

Initialize Memory: For each column (N.1, F, S, N.2, F, S, N.3, F, S), start with a default value of 0.

Value Update: When you encounter an explicit handwritten number, update the "Memory" for that specific column to that number.

The Continuation Trigger: If you encounter a vertical arrow (↓), a vertical line, or a ditto mark ("):

DO NOT use 0.

DO NOT leave it blank.

ACTION: Populate the cell with the current value held in Memory for that column.

Persistent State: Keep using the "Memory" value for every subsequent row until a new explicit number is written or the sheet ends.

Sheet-End Continuity: If an arrow or line continues to the very last row of the sheet without a new number appearing, you must continue to fill that value until the final row (e.g., Row 25).

Handle Struck-through/Crossed-out Data:

Rule for Overwritten/Struck-through Data:

Visual Conflict Check: For every cell, check if there is any horizontal, diagonal, or "scribble" ink overlapping the digits.

The "Ink Overrides Text" Rule: If you see lines drawn through or over a number (even if the number is still legible), you must prioritize the strike-through marks as a "Deletion Command."

Output: In these cases, ignore the underlying digits and record the value as 0. Treat "ink on top of text" as a manual override to zero.

Handle Empty Cells:

If a cell is blank and does not have a continuity marker (arrow) passing through it, record it as 0.

Preserve Serial Numbers:

Record the "S.N" (Serial Number) exactly as written on the page. If the handwriting skips a number or uses a non-sequential format, do not correct it. Mirror the sheet exactly.

No Hallucinations:

If a value is illegible, mark it as [?]. Do not guess.

Output ONLY the Markdown table. Do not provide an introduction or summary.
'''

        # ✅ Step 3: API Request
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "qwen-vl-plus",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            "temperature": 0
        }

        response = requests.post(BASE_URL, headers=headers, json=payload, timeout=120)

        # ✅ Step 4: Handle response
        if response.status_code == 200:
            result = response.json()
            output = result["choices"][0]["message"]["content"]

            data = _extract_data_rows(output)
            if not data:
                save_llm_output(output, {"error": "Could not parse rows from LLM output"}, image_name="parse_failed")
                return None

            # ✅ Step 5: Apply logic directly
            # Removed the skip of first row because the prompt "Start from S-1" 
            # typically results in the first element being the data row.
            
            processed_data = apply_continuation_logic(data)
            
            # ✅ Step 6: Save LLM output and processed data to JSON files
            save_llm_output(output, processed_data, image_name="extraction")
            
            return processed_data

        else:
            save_llm_output(
                response.text,
                {"error": f"HTTP {response.status_code}"},
                image_name="api_failed",
            )
            return None

    except Exception as e:
        save_llm_output(str(e), {"error": "Unhandled extractor exception"}, image_name="exception")
        return None