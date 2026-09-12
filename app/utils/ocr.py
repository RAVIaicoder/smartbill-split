"""
Receipt OCR helper.

Uses pytesseract (wraps the Tesseract OCR engine). Tesseract itself is a
system binary, not a Python package, so it must be installed separately:
    Ubuntu/Debian:  sudo apt-get install tesseract-ocr
    macOS:          brew install tesseract
    Windows:        https://github.com/UB-Mannheim/tesseract/wiki

If the binary isn't found, this module fails gracefully and the caller
falls back to manual bill-amount entry - OCR is a convenience, never a
blocker.
"""

import re

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# Matches amounts like 1,234.50 / 250 / Rs. 899.00 / INR 45
AMOUNT_PATTERN = re.compile(r"(?:rs\.?|inr|₹)?\s?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)", re.IGNORECASE)
TOTAL_KEYWORDS = ("total", "grand total", "amount due", "net payable", "amount")


def extract_text(image_path: str) -> str:
    if not OCR_AVAILABLE:
        return ""
    try:
        return pytesseract.image_to_string(Image.open(image_path))
    except Exception:
        # Tesseract binary missing, corrupt image, unsupported format, etc.
        return ""


def guess_total_amount(text: str):
    """Best-effort guess of the bill total from raw OCR text."""
    if not text:
        return None
    lines = [l.strip() for l in text.lower().splitlines() if l.strip()]
    candidates = []
    for line in lines:
        if any(k in line for k in TOTAL_KEYWORDS):
            for m in AMOUNT_PATTERN.finditer(line):
                val = m.group(1).replace(",", "")
                try:
                    candidates.append(float(val))
                except ValueError:
                    continue
    if candidates:
        return max(candidates)  # "total" lines - take the largest match
    # fallback: largest number anywhere in the receipt
    all_amounts = []
    for line in lines:
        for m in AMOUNT_PATTERN.finditer(line):
            val = m.group(1).replace(",", "")
            try:
                all_amounts.append(float(val))
            except ValueError:
                continue
    return max(all_amounts) if all_amounts else None


def scan_receipt(image_path: str):
    text = extract_text(image_path)
    return {
        "ocr_available": OCR_AVAILABLE,
        "raw_text": text,
        "guessed_amount": guess_total_amount(text),
    }
