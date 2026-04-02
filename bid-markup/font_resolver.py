"""
Font resolver for bid markup tool.
Auto-downloads matching fonts from Google Fonts when a PDF uses a font we don't have locally.
Falls back to visually similar fonts when exact match isn't available.
"""

import os
import re
import json
import urllib.request
import zipfile
import io

FONTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
CACHE_FILE = os.path.join(FONTS_DIR, "_google_fonts_cache.json")

# Manual fallback map: common PDF fonts → Google Fonts equivalents
FALLBACK_MAP = {
    # Sans-serif families
    'arial': 'Arimo',
    'helvetica': 'Arimo',
    'calibri': 'Carlito',
    'verdana': 'Open Sans',
    'tahoma': 'Open Sans',
    'trebuchetms': 'Open Sans',
    'segoeui': 'Open Sans',
    'dejavusans': 'Open Sans',
    'dejavusanscondensed': 'Open Sans Condensed',
    'freesans': 'Open Sans',
    'liberationsans': 'Arimo',
    'roboto': 'Roboto',
    'lato': 'Lato',
    'montserrat': 'Montserrat',
    'poppins': 'Poppins',
    'raleway': 'Raleway',
    'sourcesanspro': 'Source Sans 3',
    'nunitosans': 'Nunito Sans',
    
    # Serif families
    'timesnewroman': 'Tinos',
    'times': 'Tinos',
    'georgia': 'Tinos',
    'cambria': 'Caladea',
    'garamond': 'EB Garamond',
    'dejavuserif': 'Tinos',
    'liberationserif': 'Tinos',
    'freeserif': 'Tinos',
    'palatino': 'EB Garamond',
    
    # Monospace
    'couriernew': 'Courier Prime',
    'courier': 'Courier Prime',
    'couriernormal': 'Courier Prime',
    'consolas': 'Cousine',
    'dejavusansmono': 'Cousine',
    'liberationmono': 'Cousine',
    
    # Helvetica variants
    'helveticanormal': 'Arimo',
    'helvetica,bold': 'Arimo',
    'helveticanormal,bold': 'Arimo',
    'helveticanormalbold': 'Arimo',
}


def _normalize_name(name):
    """Normalize font name for matching: lowercase, remove spaces/hyphens/weight suffixes."""
    clean = name.split('+')[-1] if '+' in name else name
    # Remove weight/style suffixes
    for suffix in ['Bold', 'Italic', 'Light', 'Medium', 'Semibold', 'SemiBold', 
                   'ExtraBold', 'Black', 'Thin', 'Regular', 'Normal', 'Oblique', 'Condensed']:
        clean = clean.replace(suffix, '')
    # Remove separators (including commas from font names like "Helvetica-Normal,Bold")
    clean = re.sub(r'[-_\s,]', '', clean).lower().strip()
    return clean


def _is_bold(font_name):
    """Check if font name indicates bold weight."""
    return bool(re.search(r'(?i)(bold|black|extrabold|semibold|heavy)', font_name))


def _is_italic(font_name):
    """Check if font name indicates italic."""
    return bool(re.search(r'(?i)(italic|oblique)', font_name))


def _get_google_fonts_list():
    """Get list of Google Fonts families (cached)."""
    if os.path.exists(CACHE_FILE):
        mtime = os.path.getmtime(CACHE_FILE)
        import time
        if time.time() - mtime < 86400 * 7:  # Cache for 7 days
            with open(CACHE_FILE) as f:
                return json.load(f)
    
    try:
        url = "https://fonts.google.com/metadata/fonts"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        data = urllib.request.urlopen(req, timeout=10).read().decode()
        if data.startswith(")]}'"):
            data = data[5:]
        meta = json.loads(data)
        families = [f['family'] for f in meta.get('familyMetadataList', [])]
        
        os.makedirs(FONTS_DIR, exist_ok=True)
        with open(CACHE_FILE, 'w') as f:
            json.dump(families, f)
        
        return families
    except Exception as e:
        print(f"Warning: Could not fetch Google Fonts list: {e}")
        return []


def _download_google_font(family_name):
    """Download a font family from Google Fonts. Returns dict of style → file path."""
    os.makedirs(FONTS_DIR, exist_ok=True)
    
    # Check if already downloaded
    existing = {}
    for f in os.listdir(FONTS_DIR):
        if f.startswith(family_name.replace(' ', '')) and f.endswith('.ttf'):
            if 'Bold' in f:
                existing['bold'] = os.path.join(FONTS_DIR, f)
            elif 'Italic' in f:
                existing['italic'] = os.path.join(FONTS_DIR, f)
            else:
                existing['regular'] = os.path.join(FONTS_DIR, f)
    if existing:
        return existing
    
    try:
        # Download via Google Fonts CSS API
        family_url = family_name.replace(' ', '+')
        css_url = f"https://fonts.googleapis.com/css2?family={family_url}:wght@400;700&display=swap"
        req = urllib.request.Request(css_url, headers={
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        })
        css = urllib.request.urlopen(req, timeout=10).read().decode()
        
        # Parse TTF/WOFF2 URLs from CSS
        font_urls = re.findall(r'src:\s*url\(([^)]+)\)', css)
        weights = re.findall(r'font-weight:\s*(\d+)', css)
        
        results = {}
        for i, url in enumerate(font_urls):
            weight = int(weights[i]) if i < len(weights) else 400
            style = 'bold' if weight >= 700 else 'regular'
            
            # Download font file
            font_data = urllib.request.urlopen(url, timeout=15).read()
            
            # Determine extension from URL
            ext = 'woff2' if '.woff2' in url else 'ttf'
            
            if ext == 'woff2':
                # Convert woff2 to ttf using fonttools
                try:
                    from fontTools.ttLib import TTFont
                    font = TTFont(io.BytesIO(font_data))
                    clean_family = family_name.replace(' ', '')
                    suffix = '-Bold' if style == 'bold' else '-Regular'
                    out_path = os.path.join(FONTS_DIR, f"{clean_family}{suffix}.ttf")
                    font.save(out_path)
                    results[style] = out_path
                    print(f"    Downloaded: {os.path.basename(out_path)}")
                except ImportError:
                    # No fonttools, save as woff2
                    clean_family = family_name.replace(' ', '')
                    suffix = '-Bold' if style == 'bold' else '-Regular'
                    out_path = os.path.join(FONTS_DIR, f"{clean_family}{suffix}.woff2")
                    with open(out_path, 'wb') as f:
                        f.write(font_data)
                    results[style] = out_path
            else:
                clean_family = family_name.replace(' ', '')
                suffix = '-Bold' if style == 'bold' else '-Regular'
                out_path = os.path.join(FONTS_DIR, f"{clean_family}{suffix}.ttf")
                with open(out_path, 'wb') as f:
                    f.write(font_data)
                results[style] = out_path
                print(f"    Downloaded: {os.path.basename(out_path)}")
        
        return results
        
    except Exception as e:
        print(f"    Warning: Could not download '{family_name}': {e}")
        return {}


def resolve_font(pdf_font_name):
    """
    Resolve a PDF font name to a local .ttf file path.
    
    Strategy:
    1. Check local fonts directory for exact match
    2. Check FONT_MAP for known mappings
    3. Search Google Fonts for matching family
    4. Use fallback map for common substitutions
    5. Download from Google Fonts
    6. Fall back to OpenSans as last resort
    
    Returns: path to .ttf file, or None
    """
    bold = _is_bold(pdf_font_name)
    normalized = _normalize_name(pdf_font_name)
    
    # 1. Check existing local fonts
    for f in os.listdir(FONTS_DIR):
        if not f.endswith('.ttf'):
            continue
        f_norm = _normalize_name(f.replace('.ttf', ''))
        if normalized == f_norm or normalized in f_norm:
            # Check bold match
            if bold and 'Bold' in f:
                return os.path.join(FONTS_DIR, f)
            elif not bold and 'Bold' not in f:
                return os.path.join(FONTS_DIR, f)
    
    # Also check with bold tolerance (bold file is better than nothing)
    for f in os.listdir(FONTS_DIR):
        if not f.endswith('.ttf'):
            continue
        f_norm = _normalize_name(f.replace('.ttf', ''))
        if normalized == f_norm or normalized in f_norm:
            return os.path.join(FONTS_DIR, f)
    
    # 2. Try Google Fonts direct name match
    google_families = _get_google_fonts_list()
    
    # Build a lookup dict
    gf_lookup = {}
    for family in google_families:
        key = re.sub(r'[-_\s]', '', family).lower()
        gf_lookup[key] = family
    
    # Try direct match
    if normalized in gf_lookup:
        family = gf_lookup[normalized]
        print(f"    Auto-resolving '{pdf_font_name}' → Google Fonts '{family}'")
        downloaded = _download_google_font(family)
        style = 'bold' if bold else 'regular'
        if style in downloaded:
            return downloaded[style]
        if downloaded:
            return list(downloaded.values())[0]
    
    # 3. Try fallback map
    if normalized in FALLBACK_MAP:
        family = FALLBACK_MAP[normalized]
        print(f"    Fallback: '{pdf_font_name}' → '{family}'")
        downloaded = _download_google_font(family)
        style = 'bold' if bold else 'regular'
        if style in downloaded:
            return downloaded[style]
        if downloaded:
            return list(downloaded.values())[0]
    
    # 4. Fuzzy match against Google Fonts
    for gf_key, gf_family in gf_lookup.items():
        if len(normalized) > 3 and (normalized in gf_key or gf_key in normalized):
            print(f"    Fuzzy match: '{pdf_font_name}' → Google Fonts '{gf_family}'")
            downloaded = _download_google_font(gf_family)
            style = 'bold' if bold else 'regular'
            if style in downloaded:
                return downloaded[style]
            if downloaded:
                return list(downloaded.values())[0]
    
    # 5. Last resort: OpenSans
    fallback = os.path.join(FONTS_DIR, 'OpenSans-Bold.ttf' if bold else 'OpenSans-Regular.ttf')
    if os.path.exists(fallback):
        print(f"    No match for '{pdf_font_name}', using OpenSans fallback")
        return fallback
    
    return None


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        font_name = ' '.join(sys.argv[1:])
        result = resolve_font(font_name)
        print(f"\n'{font_name}' → {result}")
    else:
        # Test common fonts
        test_fonts = [
            'Arial', 'Arial-Bold', 'Helvetica', 'TimesNewRoman',
            'Calibri', 'DejaVuSansCondensed-Bold', 'OpenSans',
            'Roboto-Medium', 'BAAAAA+SomeWeirdFont',
        ]
        for font in test_fonts:
            result = resolve_font(font)
            print(f"  {font:35s} → {os.path.basename(result) if result else 'NONE'}")
