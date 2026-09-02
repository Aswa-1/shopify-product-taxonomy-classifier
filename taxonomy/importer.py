import re
import urllib.request
import logging
from pathlib import Path

from django.db import transaction, IntegrityError

from products.services.normalizer import clean_text
from .models import TaxonomyCategory, TaxonomyAttribute, TaxonomyAttributeValue

logger = logging.getLogger(__name__)

CATEGORIES_URL = 'https://raw.githubusercontent.com/Shopify/product-taxonomy/main/dist/en/categories.txt'
ATTRIBUTES_URL = 'https://raw.githubusercontent.com/Shopify/product-taxonomy/main/dist/en/attributes.txt'
PROJECT_ROOT = Path(__file__).resolve().parent.parent


ATTRIBUTE_VALUE_LINE_RE = re.compile(
    r'^(?P<gid>gid://shopify/TaxonomyValue/\S+)\s*:\s*(?P<value>.+?)\s*\[(?P<attribute>[^\]]+)\]\s*$'
)


def parse_attribute_value_line(line):
    """Parse a Shopify taxonomy value line into gid/value/attribute parts."""
    if not line or not line.strip() or line.strip().startswith('#'):
        return None

    cleaned = line.strip()
    match = ATTRIBUTE_VALUE_LINE_RE.match(cleaned)
    if not match:
        return None

    gid = match.group('gid').strip()
    value = clean_text(match.group('value')).strip()
    attribute_name = clean_text(match.group('attribute')).strip()

    if not gid or not value or not attribute_name:
        return None

    return {
        'gid': gid,
        'value': value,
        'attribute_name': attribute_name,
    }


def _normalize_taxonomy_value(value):
    """Use the existing project normalization approach for text normalization."""
    cleaned = clean_text(value)
    return cleaned.casefold() if cleaned else ''


def import_shopify_attribute_values(file_path=None):
    """Import Shopify taxonomy attribute values from the root attribute_values.txt file."""
    if file_path is None:
        file_path = PROJECT_ROOT / 'attribute_values.txt'

    file_path = Path(file_path)
    total_lines = 0
    successfully_imported = 0
    skipped = 0
    unmatched_attributes = 0
    invalid_lines = 0

    attributes_by_name = {
        _normalize_taxonomy_value(name): attribute
        for attribute in TaxonomyAttribute.objects.all()
        for name in [attribute.name]
    }
    pending_values = []

    try:
        with file_path.open('r', encoding='utf-8') as fh:
            for raw_line in fh:
                total_lines += 1
                parsed = parse_attribute_value_line(raw_line)

                if parsed is None:
                    invalid_lines += 1
                    continue

                attribute_name = parsed['attribute_name']
                attribute = attributes_by_name.get(_normalize_taxonomy_value(attribute_name))
                if attribute is None:
                    unmatched_attributes += 1
                    skipped += 1
                    continue

                normalized_value = _normalize_taxonomy_value(parsed['value'])
                if not normalized_value:
                    invalid_lines += 1
                    continue

                pending_values.append(TaxonomyAttributeValue(
                    attribute=attribute,
                    gid=parsed['gid'],
                    value=parsed['value'],
                    normalized_value=normalized_value,
                ))

        existing_keys = set(
            TaxonomyAttributeValue.objects.values_list('attribute_id', 'normalized_value')
        )
        values_to_create = []
        seen_keys = set()
        for value_obj in pending_values:
            key = (value_obj.attribute_id, value_obj.normalized_value)
            if key in existing_keys or key in seen_keys:
                skipped += 1
                continue
            seen_keys.add(key)
            values_to_create.append(value_obj)

        try:
            TaxonomyAttributeValue.objects.bulk_create(values_to_create, batch_size=2000)
            successfully_imported = len(values_to_create)
        except IntegrityError:
            # Existing rows can race with an import; preserve the import's safe behavior.
            for value_obj in values_to_create:
                try:
                    TaxonomyAttributeValue.objects.get_or_create(
                        attribute_id=value_obj.attribute_id,
                        normalized_value=value_obj.normalized_value,
                        defaults={'gid': value_obj.gid, 'value': value_obj.value},
                    )
                    successfully_imported += 1
                except IntegrityError:
                    skipped += 1
        return {
            'total_lines': total_lines,
            'successfully_imported': successfully_imported,
            'skipped': skipped,
            'unmatched_attributes': unmatched_attributes,
            'invalid_lines': invalid_lines,
        }
    except FileNotFoundError:
        logger.warning(f"Attribute values file not found: {file_path}")
        return {
            'total_lines': 0,
            'successfully_imported': 0,
            'skipped': 0,
            'unmatched_attributes': 0,
            'invalid_lines': 0,
        }


def import_shopify_taxonomy(cat_url=CATEGORIES_URL, attr_url=ATTRIBUTES_URL):
    """
    Imports the official English Shopify Product Taxonomy from GitHub.
    Populates TaxonomyCategory with parent-child relationships and levels.
    Populates TaxonomyAttribute with global/category attributes.
    """
    logger.info("Starting Shopify Taxonomy Import from official GitHub distribution...")

    req = urllib.request.Request(cat_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as resp:
        cat_lines = resp.read().decode('utf-8').splitlines()

    parsed_categories = []
    path_to_dict = {}

    for line in cat_lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split(' : ', 1)
        if len(parts) == 2:
            gid, full_path = parts[0].strip(), parts[1].strip()
            path_segments = [p.strip() for p in full_path.split('>')]
            cat_name = path_segments[-1]
            cat_id = gid.split('/')[-1]
            parent_path = ' > '.join(path_segments[:-1]) if len(path_segments) > 1 else None
            level = len(path_segments)

            entry = {
                'shopify_id': cat_id,
                'gid': gid,
                'name': cat_name,
                'full_path': full_path,
                'parent_path': parent_path,
                'level': level,
            }
            parsed_categories.append(entry)
            path_to_dict[full_path] = entry

    logger.info(f"Parsed {len(parsed_categories)} categories from categories.txt")

    # Step 1: Bulk Upsert / Insert Categories without parent foreign key first
    existing_map = {c.shopify_id: c for c in TaxonomyCategory.objects.all()}
    categories_to_create = []
    
    with transaction.atomic():
        for cat_data in parsed_categories:
            sid = cat_data['shopify_id']
            if sid not in existing_map:
                obj = TaxonomyCategory(
                    shopify_id=sid,
                    gid=cat_data['gid'],
                    name=cat_data['name'],
                    full_path=cat_data['full_path'],
                    level=cat_data['level'],
                )
                categories_to_create.append(obj)

        if categories_to_create:
            TaxonomyCategory.objects.bulk_create(categories_to_create, batch_size=2000)

        # Re-query all categories into map: full_path -> TaxonomyCategory instance
        db_categories = {c.full_path: c for c in TaxonomyCategory.objects.all()}

        # Step 2: Set parent FK
        updates = []
        for cat_data in parsed_categories:
            cat_obj = db_categories.get(cat_data['full_path'])
            if cat_obj and cat_data['parent_path']:
                parent_obj = db_categories.get(cat_data['parent_path'])
                if parent_obj and cat_obj.parent_id != parent_obj.id:
                    cat_obj.parent = parent_obj
                    updates.append(cat_obj)

        if updates:
            TaxonomyCategory.objects.bulk_update(updates, ['parent'], batch_size=2000)

    logger.info(f"Successfully processed {len(parsed_categories)} categories in database.")

    # Step 3: Import Attributes
    req_attr = urllib.request.Request(attr_url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req_attr) as resp_attr:
            attr_lines = resp_attr.read().decode('utf-8').splitlines()

        attributes_to_create = []
        existing_attrs = set(TaxonomyAttribute.objects.values_list('gid', flat=True))

        for line in attr_lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(' : ', 1)
            if len(parts) == 2:
                gid, attr_name = parts[0].strip(), parts[1].strip()
                if gid not in existing_attrs:
                    attributes_to_create.append(
                        TaxonomyAttribute(gid=gid, name=attr_name, value_type='string')
                    )

        if attributes_to_create:
            with transaction.atomic():
                TaxonomyAttribute.objects.bulk_create(attributes_to_create, batch_size=2000)
        logger.info(f"Successfully imported {len(attributes_to_create)} attributes.")
    except Exception as e:
        logger.warning(f"Attribute import warning: {e}")

    return {
        'total_categories': len(parsed_categories),
        'total_attributes': TaxonomyAttribute.objects.count(),
    }
