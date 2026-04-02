"""
OCR support for bid markup pipeline.
Detects image-based PDFs and extracts text + positions using Tesseract.
For markup: overlays new amounts on the original scanned image.
"""

import fitz
import re
import os
import io

try:
    import pytesseract
    from PIL import Image
    HAS_OCR = True
except ImportError:
    HAS_OCR = False


def is_image_pdf(pdf_path):
    """
    Detect if a PDF is image-based (scanned) vs text-based.
    Returns True if the PDF has very little extractable text relative to its page count.
    """
    doc = fitz.open(pdf_path)
    total_text = ""
    page_count = doc.page_count
    for page in doc:
        total_text += page.get_text()
    doc.close()
    
    # If we get very little text (< 50 chars per page), it's likely scanned
    chars_per_page = len(total_text.strip()) / max(page_count, 1)
    return chars_per_page < 50


def ocr_page(page, dpi=300):
    """
    Run OCR on a PDF page. Returns list of detected text blocks with positions.
    Each block: {text, x, y, w, h, conf}
    """
    if not HAS_OCR:
        raise RuntimeError("OCR not available. Install: pip3 install pytesseract pillow && brew install tesseract")
    
    # Render page to image
    pix = page.get_pixmap(dpi=dpi)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    
    # Run Tesseract with detailed output
    ocr_data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    
    # Scale factor: OCR coordinates are in pixels at the given DPI
    # PDF coordinates are in points (72 per inch)
    scale = 72.0 / dpi
    
    blocks = []
    n = len(ocr_data['text'])
    
    # Group words into lines by block_num + line_num
    lines = {}
    for i in range(n):
        text = ocr_data['text'][i].strip()
        conf = int(ocr_data['conf'][i])
        if not text or conf < 30:  # Skip low-confidence junk
            continue
        
        key = (ocr_data['block_num'][i], ocr_data['line_num'][i])
        if key not in lines:
            lines[key] = {
                'words': [],
                'x': ocr_data['left'][i] * scale,
                'y': ocr_data['top'][i] * scale,
                'x2': (ocr_data['left'][i] + ocr_data['width'][i]) * scale,
                'y2': (ocr_data['top'][i] + ocr_data['height'][i]) * scale,
            }
        
        lines[key]['words'].append({
            'text': text,
            'x': ocr_data['left'][i] * scale,
            'y': ocr_data['top'][i] * scale,
            'w': ocr_data['width'][i] * scale,
            'h': ocr_data['height'][i] * scale,
            'conf': conf,
        })
        # Expand line bbox
        lines[key]['x'] = min(lines[key]['x'], ocr_data['left'][i] * scale)
        lines[key]['y'] = min(lines[key]['y'], ocr_data['top'][i] * scale)
        lines[key]['x2'] = max(lines[key]['x2'], (ocr_data['left'][i] + ocr_data['width'][i]) * scale)
        lines[key]['y2'] = max(lines[key]['y2'], (ocr_data['top'][i] + ocr_data['height'][i]) * scale)
    
    for key in sorted(lines.keys()):
        line = lines[key]
        line_text = ' '.join(w['text'] for w in line['words'])
        blocks.append({
            'text': line_text,
            'x': line['x'],
            'y': line['y'],
            'x2': line['x2'],
            'y2': line['y2'],
            'words': line['words'],
        })
    
    return blocks


def ocr_extract_text(pdf_path, dpi=300):
    """
    Extract all text from an image PDF using OCR.
    Returns full text string (for pricing extraction).
    """
    doc = fitz.open(pdf_path)
    full_text = ""
    for page in doc:
        blocks = ocr_page(page, dpi=dpi)
        for block in blocks:
            full_text += block['text'] + '\n'
        full_text += '\n--- PAGE BREAK ---\n'
    doc.close()
    return full_text


def markup_image_pdf(input_path, output_path, markup=0.30, dpi=300):
    """
    Mark up dollar amounts in an image-based (scanned) PDF.
    Strategy: OCR to find amounts + positions, then overlay white boxes + new text
    on the original scanned image. Original scan stays intact underneath.
    
    Returns list of changes made.
    """
    if not HAS_OCR:
        raise RuntimeError("OCR not available. Install: pip3 install pytesseract pillow && brew install tesseract")
    
    doc = fitz.open(input_path)
    money_pat = re.compile(r'\$?([\d,]+\.\d{2})')
    changes = []
    
    for page in doc:
        blocks = ocr_page(page, dpi=dpi)
        
        for block in blocks:
            text = block['text']
            if '%' in text:
                continue
            
            matches = list(money_pat.finditer(text))
            if not matches:
                continue
            
            # Find which words contain dollar amounts
            for word_info in block['words']:
                word = word_info['text']
                money_match = money_pat.search(word)
                if not money_match:
                    continue
                
                raw = money_match.group(1).replace(',', '')
                amount = float(raw)
                if amount == 0:
                    continue
                
                new_amount = round(amount * (1 + markup), 2)
                has_dollar = '$' in word
                new_text = f"${new_amount:,.2f}" if has_dollar else f"{new_amount:,.2f}"
                
                # Position for overlay
                bbox = fitz.Rect(
                    word_info['x'],
                    word_info['y'],
                    word_info['x'] + word_info['w'],
                    word_info['y'] + word_info['h']
                )
                
                # Expand bbox slightly for clean coverage
                bbox.x0 -= 1
                bbox.y0 -= 1
                bbox.x1 += 1
                bbox.y1 += 1
                
                # White out old amount
                shape = page.new_shape()
                shape.draw_rect(bbox)
                shape.finish(color=(1, 1, 1), fill=(1, 1, 1))
                shape.commit()
                
                # Estimate font size from word height
                font_size = word_info['h'] * 0.85
                if font_size < 6:
                    font_size = 8
                if font_size > 20:
                    font_size = 14
                
                # Insert new text (right-aligned)
                font_obj = fitz.Font("helv")
                tw = font_obj.text_length(new_text, fontsize=font_size)
                x = bbox.x1 - tw - 1
                y = bbox.y0 + font_size * 0.85
                
                page.insert_text(
                    (max(bbox.x0, x), y),
                    new_text,
                    fontname="helv",
                    fontsize=font_size,
                    color=(0, 0, 0)
                )
                
                changes.append({
                    'original': amount,
                    'marked_up': new_amount,
                    'word': word,
                })
    
    doc.save(output_path)
    doc.close()
    return changes


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        print(f"Checking: {pdf_path}")
        print(f"Is image PDF: {is_image_pdf(pdf_path)}")
        
        if is_image_pdf(pdf_path):
            print("\nOCR text extraction:")
            text = ocr_extract_text(pdf_path)
            print(text[:2000])
        else:
            print("Text-based PDF — no OCR needed")
