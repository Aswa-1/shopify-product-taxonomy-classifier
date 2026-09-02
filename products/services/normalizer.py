import re
import hashlib
import pandas as pd

def clean_text(text):
    """
    Normalizes product text: removes HTML, replaces Excel _x000D_, 
    collapses multiple spaces/newlines, strips leading/trailing whitespace.
    Returns empty string if null/NaN/None.
    """
    if text is None or pd.isna(text):
        return ""
    
    text = str(text)
    # Replaces Excel carriage returns
    text = text.replace('_x000D_', '\n')
    
    # Strip HTML tags if present
    text = re.sub(r'<[^>]+>', ' ', text)
    
    # Replace non-breaking spaces and clean whitespace
    text = text.replace('\xa0', ' ')
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned = ' '.join(lines)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned


def normalize_product_dict(raw_row):
    """
    Normalizes a row dictionary from Excel or a Product instance dict into a clean product structure.
    Calculates content hash of normalized data.
    """
    if hasattr(raw_row, '__dict__'):
        # Handled Product instance
        p = raw_row
        cleaned_row = {
            'Product Number': getattr(p, 'product_number', ''),
            'Model Number': getattr(p, 'model_number', ''),
            'Product Name': getattr(p, 'title', ''),
            'Product Description': getattr(p, 'description', ''),
            'Bullets': getattr(p, 'bullets', ''),
            'Product Category': getattr(p, 'product_category', ''),
            'Product Sub Category': getattr(p, 'product_subcategory', ''),
            'Collection Name': getattr(p, 'collection_name', ''),
            'Brand': getattr(p, 'brand', ''),
            'Product Color': getattr(p, 'color', ''),
            'Materials': getattr(p, 'materials', ''),
            'Product Dimensions': getattr(p, 'dimensions', ''),
            'Set Includes': getattr(p, 'set_includes', ''),
            'Assembly Required': getattr(p, 'assembly_required', ''),
            'Is a Set': getattr(p, 'is_set', ''),
            'Stackable': getattr(p, 'stackable', ''),
            'Country Of Origin': getattr(p, 'country_of_origin', ''),
            'Product URL': getattr(p, 'product_url', ''),
        }
    elif isinstance(raw_row, dict):
        cleaned_row = {str(k).strip(): v for k, v in raw_row.items()}
    else:
        cleaned_row = {}

    product_number = clean_text(cleaned_row.get('Product Number'))
    model_number = clean_text(cleaned_row.get('Model Number'))
    title = clean_text(cleaned_row.get('Product Name') or cleaned_row.get('title'))
    description = clean_text(cleaned_row.get('Product Description') or cleaned_row.get('description'))
    bullets = clean_text(cleaned_row.get('Bullets') or cleaned_row.get('bullets'))
    category = clean_text(cleaned_row.get('Product Category') or cleaned_row.get('product_category'))
    subcategory = clean_text(cleaned_row.get('Product Sub Category') or cleaned_row.get('product_subcategory'))
    collection = clean_text(cleaned_row.get('Collection Name') or cleaned_row.get('collection_name'))
    color = clean_text(cleaned_row.get('Product Color') or cleaned_row.get('Color Collection') or cleaned_row.get('color'))
    materials = clean_text(cleaned_row.get('Materials') or cleaned_row.get('materials'))
    dimensions = clean_text(cleaned_row.get('Product Dimensions') or cleaned_row.get('dimensions'))
    set_includes = clean_text(cleaned_row.get('Set Includes') or cleaned_row.get('set_includes'))
    assembly = clean_text(cleaned_row.get('Assembly Required') or cleaned_row.get('assembly_required'))
    is_set = clean_text(cleaned_row.get('Is a Set') or cleaned_row.get('is_set'))
    stackable = clean_text(cleaned_row.get('Stackable') or cleaned_row.get('stackable'))
    country = clean_text(cleaned_row.get('Country Of Origin') or cleaned_row.get('country_of_origin'))
    url = clean_text(cleaned_row.get('Product URL') or cleaned_row.get('product_url'))
    
    # Extract images (Image 1 to Image 20)
    images = []
    for i in range(1, 21):
        img_key = f'Image {i}'
        img_val = clean_text(cleaned_row.get(img_key))
        if img_val and img_val.startswith('http'):
            images.append(img_val)

    # Calculate content hash for deduplication/caching
    hash_str = f"{title}|{description}|{category}|{subcategory}|{materials}|{color}|{dimensions}"
    content_hash = hashlib.md5(hash_str.encode('utf-8')).hexdigest()

    return {
        'product_number': product_number,
        'model_number': model_number,
        'title': title,
        'description': description,
        'bullets': bullets,
        'product_category': category,
        'product_subcategory': subcategory,
        'collection_name': collection,
        'brand': clean_text(cleaned_row.get('Brand', 'Modway')),
        'color': color,
        'materials': materials,
        'dimensions': dimensions,
        'set_includes': set_includes,
        'assembly_required': assembly,
        'is_set': is_set,
        'stackable': stackable,
        'country_of_origin': country,
        'product_url': url,
        'images': images,
        'content_hash': content_hash,
        'raw_data': {k: (None if pd.isna(v) else v) for k, v in cleaned_row.items()}
    }
