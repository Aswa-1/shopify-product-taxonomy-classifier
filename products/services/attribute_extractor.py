import re
from difflib import SequenceMatcher
from collections import namedtuple

from django.db import connections
from django.db.models import Q

from taxonomy.models import TaxonomyAttribute, TaxonomyAttributeValue, TaxonomyCategory


_TaxonomyValueCandidate = namedtuple(
    '_TaxonomyValueCandidate',
    ['gid', 'value', 'normalized_value'],
)
_taxonomy_value_lookup_cache = {}


def _normalize_value_for_match(value):
    if value is None:
        return ''
    text = str(value)
    text = text.replace('_x000D_', '\n')
    text = re.sub(r'<[^>]+>', ' ', text)
    text = text.replace('\xa0', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    return text.casefold()


def _normalize_attribute_name(value):
    return _normalize_value_for_match(value)


def _get_relevant_taxonomy_value_lookup(category_obj, attribute_names=None):
    if not category_obj:
        return [], {}

    requested_names = tuple(sorted(
        _normalize_attribute_name(name) for name in (attribute_names or [])
    ))
    database_alias = category_obj._state.db or 'default'
    database_name = connections[database_alias].settings_dict.get('NAME')
    cache_key = (database_alias, database_name, category_obj.full_path, requested_names)
    cached = _taxonomy_value_lookup_cache.get(cache_key)
    if cached is not None:
        return cached

    relevant_attrs = list(_get_relevant_taxonomy_attributes(category_obj, requested_names))
    if not relevant_attrs:
        result = ([], {})
        _taxonomy_value_lookup_cache[cache_key] = result
        return result

    attr_ids = [attr.id for attr in relevant_attrs]
    values = (
        TaxonomyAttributeValue.objects
        .filter(attribute_id__in=attr_ids)
        .values('attribute_id', 'gid', 'value', 'normalized_value')
    )

    lookup = {}
    attr_names = {attr.id: _normalize_attribute_name(attr.name) for attr in relevant_attrs}
    for value in values.iterator():
        candidate = _TaxonomyValueCandidate(
            gid=value['gid'],
            value=value['value'],
            normalized_value=value['normalized_value'],
        )
        bucket = lookup.setdefault(attr_names[value['attribute_id']], {'exact': {}, 'values': []})
        normalized_value = _normalize_value_for_match(value['normalized_value'] or value['value'])
        bucket['exact'][normalized_value] = candidate
        bucket['values'].append(candidate)

    result = (relevant_attrs, lookup)
    _taxonomy_value_lookup_cache[cache_key] = result
    return result


def _get_relevant_taxonomy_attributes(category_obj, attribute_names=None):
    if not category_obj:
        return TaxonomyAttribute.objects.none()

    path_parts = [part.strip() for part in category_obj.full_path.split('>')]
    category_paths = [' > '.join(path_parts[:index]) for index in range(1, len(path_parts) + 1)]
    category_ids = TaxonomyCategory.objects.filter(
        full_path__in=category_paths
    ).values_list('id', flat=True)

    query = TaxonomyAttribute.objects.filter(
        Q(category_id__in=category_ids) | Q(category__isnull=True)
    ).only('id', 'name', 'gid')
    if attribute_names:
        name_filter = Q()
        for name in attribute_names:
            name_filter |= Q(name__iexact=name)
        query = query.filter(name_filter)
    return query


def map_source_value_to_taxonomy_value(attribute_name, source_value, category_full_path=None, category_obj=None, value_lookup=None):
    """Match a product-derived value against official Shopify taxonomy values."""
    if not attribute_name or source_value is None:
        return None

    source_value = str(source_value).strip()
    if not source_value:
        return None

    normalized_source = _normalize_value_for_match(source_value)
    if not normalized_source:
        return None

    if value_lookup is not None:
        bucket = value_lookup.get(_normalize_attribute_name(attribute_name), {})
        exact_candidate = bucket.get('exact', {}).get(normalized_source)
        if exact_candidate is not None:
            return exact_candidate
        candidates = bucket.get('values', [])
    else:
        query = TaxonomyAttributeValue.objects.select_related('attribute').filter(attribute__name__iexact=attribute_name)

        if category_obj is not None:
            category_ids = []
            current = category_obj
            while current is not None:
                category_ids.append(current.id)
                current = current.parent
            query = query.filter(Q(attribute__category_id__in=category_ids) | Q(attribute__category__isnull=True))

        candidates = list(query)

    if not candidates:
        return None

    best_match = None
    best_ratio = 0.0
    for candidate in candidates:
        candidate_norm = _normalize_value_for_match(candidate.normalized_value or candidate.value)
        if not candidate_norm:
            continue
        ratio = SequenceMatcher(None, normalized_source, candidate_norm).ratio()
        if ratio > best_ratio and ratio >= 0.92:
            best_ratio = ratio
            best_match = candidate

    return best_match


def _apply_taxonomy_mapping(product_dict, category_obj):
    if not category_obj:
        return {}

    value_sources = {
        'Material': product_dict.get('materials'),
        'Color': product_dict.get('color'),
        'Dimensions': product_dict.get('dimensions'),
        'Assembly Required': (
            'Yes' if str(product_dict.get('assembly_required')).strip().upper() == 'Y'
            else 'No' if str(product_dict.get('assembly_required')).strip().upper() == 'N'
            else product_dict.get('assembly_required')
        ),
        'Country of Origin': product_dict.get('country_of_origin'),
        'Is Set': product_dict.get('is_set'),
        'Stackable': product_dict.get('stackable'),
    }
    relevant_attrs, value_lookup = _get_relevant_taxonomy_value_lookup(
        category_obj,
        attribute_names=value_sources,
    )
    if not relevant_attrs:
        return {}

    mapped = {}
    for attr in relevant_attrs:
        attr_name = attr.name
        source_value = next(
            (value for name, value in value_sources.items()
             if _normalize_attribute_name(name) == _normalize_attribute_name(attr_name)),
            None,
        )
        if source_value is None:
            continue

        match = map_source_value_to_taxonomy_value(
            attr_name,
            source_value,
            category_obj=category_obj,
            value_lookup=value_lookup,
        )
        if match is None:
            continue

        exact = _normalize_value_for_match(match.normalized_value or match.value) == _normalize_value_for_match(source_value)
        mapped[attr_name] = {
            'attribute': attr.name,
            'value': str(source_value),
            'confidence': 0.95 if exact else 0.90,
            'source': 'Source Data → Shopify Taxonomy Mapping',
            'shopify_attribute_gid': attr.gid,
            'shopify_value_gid': match.gid,
        }

    return mapped


def refresh_product_attribute_mappings(product_obj, product_dict=None, persist=True):
    """Safely reprocess the existing ProductAttribute rows for a product without changing category selection."""
    if product_obj is None:
        return {'updated': 0, 'mapped': 0}

    classification = getattr(product_obj, 'classification', None)
    if classification is None or not classification.selected_category:
        return {'updated': 0, 'mapped': 0}

    if product_dict is None:
        from products.services.normalizer import normalize_product_dict

        raw_row = product_obj.raw_data if product_obj.raw_data else product_obj
        product_dict = normalize_product_dict(raw_row)

    extracted_attributes = extract_category_attributes(product_dict, classification.selected_category)
    mapped_by_name = {}
    for item in extracted_attributes:
        if item.get('shopify_value_gid'):
            mapped_by_name[_normalize_attribute_name(item['attribute'])] = item

    updated = 0
    mapped = 0

    for attr in classification.attributes.all():
        updated += 1
        mapped_item = mapped_by_name.get(_normalize_attribute_name(attr.attribute_name))

        if mapped_item:
            attr.attribute_value = mapped_item.get('value', attr.attribute_value)
            attr.confidence_score = mapped_item.get('confidence', attr.confidence_score)
            attr.source = mapped_item.get('source', attr.source)
            attr.shopify_attribute_gid = mapped_item.get('shopify_attribute_gid')
            attr.shopify_value_gid = mapped_item.get('shopify_value_gid')
            mapped += 1
        else:
            attr.attribute_value = attr.attribute_value
            attr.confidence_score = attr.confidence_score
            attr.source = attr.source
            attr.shopify_attribute_gid = None
            attr.shopify_value_gid = None

        if persist:
            attr.save(update_fields=[
                'attribute_value',
                'confidence_score',
                'source',
                'shopify_attribute_gid',
                'shopify_value_gid',
            ])

    return {'updated': updated, 'mapped': mapped}


def refresh_all_product_attribute_mappings():
    """Update existing ProductAttribute rows across all products without altering category selection."""
    from products.models import Product, ProductAttribute

    updated = 0
    mapped = 0
    pending_attributes = []
    for product in Product.objects.select_related('classification__selected_category').prefetch_related('classification__attributes'):
        result = refresh_product_attribute_mappings(product, persist=False)
        updated += result['updated']
        mapped += result['mapped']
        pending_attributes.extend(product.classification.attributes.all())

        if len(pending_attributes) >= 2000:
            ProductAttribute.objects.bulk_update(
                pending_attributes,
                ['attribute_value', 'confidence_score', 'source', 'shopify_attribute_gid', 'shopify_value_gid'],
                batch_size=2000,
            )
            pending_attributes = []

    if pending_attributes:
        ProductAttribute.objects.bulk_update(
            pending_attributes,
            ['attribute_value', 'confidence_score', 'source', 'shopify_attribute_gid', 'shopify_value_gid'],
            batch_size=2000,
        )

    return {'updated': updated, 'mapped': mapped}


def extract_category_attributes(product_dict, category_obj):
    """
    Extracts category-relevant attributes for a product based on its assigned Shopify Category.
    Returns list of dicts: [{'attribute': name, 'value': val, 'confidence': 1.0, 'source': 'Source Data'}]
    """
    attributes = []
    cat_path = category_obj.full_path.lower() if category_obj else ""

    materials = product_dict.get('materials')
    if materials:
        attributes.append({
            'attribute': 'Material',
            'value': materials,
            'confidence': 0.95,
            'source': 'Source Data (Materials)',
            'shopify_attribute_gid': None,
            'shopify_value_gid': None,
        })

    color = product_dict.get('color')
    if color:
        attributes.append({
            'attribute': 'Color',
            'value': color,
            'confidence': 0.95,
            'source': 'Source Data (Product Color)',
            'shopify_attribute_gid': None,
            'shopify_value_gid': None,
        })

    dimensions = product_dict.get('dimensions')
    if dimensions:
        attributes.append({
            'attribute': 'Dimensions',
            'value': dimensions[:200],
            'confidence': 0.90,
            'source': 'Source Data (Product Dimensions)',
            'shopify_attribute_gid': None,
            'shopify_value_gid': None,
        })

    assembly = product_dict.get('assembly_required')
    if assembly:
        val = 'Yes' if str(assembly).strip().upper() == 'Y' else ('No' if str(assembly).strip().upper() == 'N' else str(assembly))
        attributes.append({
            'attribute': 'Assembly Required',
            'value': val,
            'confidence': 1.0,
            'source': 'Source Data',
            'shopify_attribute_gid': None,
            'shopify_value_gid': None,
        })

    country = product_dict.get('country_of_origin')
    if country:
        attributes.append({
            'attribute': 'Country of Origin',
            'value': country,
            'confidence': 1.0,
            'source': 'Source Data',
            'shopify_attribute_gid': None,
            'shopify_value_gid': None,
        })

    is_set = product_dict.get('is_set')
    if is_set and str(is_set).strip().upper() in ('Y', 'YES', 'TRUE'):
        attributes.append({
            'attribute': 'Is Set',
            'value': 'Yes',
            'confidence': 1.0,
            'source': 'Source Data',
            'shopify_attribute_gid': None,
            'shopify_value_gid': None,
        })
        set_includes = product_dict.get('set_includes')
        if set_includes:
            attributes.append({
                'attribute': 'Set Components',
                'value': set_includes,
                'confidence': 0.95,
                'source': 'Source Data',
                'shopify_attribute_gid': None,
                'shopify_value_gid': None,
            })

    stackable = product_dict.get('stackable')
    if stackable and str(stackable).strip().upper() in ('Y', 'YES', 'TRUE'):
        attributes.append({
            'attribute': 'Stackable',
            'value': 'Yes',
            'confidence': 1.0,
            'source': 'Source Data',
            'shopify_attribute_gid': None,
            'shopify_value_gid': None,
        })

    title_desc = f"{product_dict.get('title', '')} {product_dict.get('description', '')}".lower()

    if 'sofa' in cat_path or 'sectional' in cat_path:
        if '3-seater' in title_desc or 'three seater' in title_desc:
            attributes.append({'attribute': 'Seating Capacity', 'value': '3', 'confidence': 0.90, 'source': 'Text Inference', 'shopify_attribute_gid': None, 'shopify_value_gid': None})
        elif '2-seater' in title_desc or 'loveseat' in title_desc or 'two seater' in title_desc:
            attributes.append({'attribute': 'Seating Capacity', 'value': '2', 'confidence': 0.90, 'source': 'Text Inference', 'shopify_attribute_gid': None, 'shopify_value_gid': None})

    mapped_attrs = _apply_taxonomy_mapping(product_dict, category_obj)
    if mapped_attrs:
        final_attributes = []
        seen = set()
        for item in attributes:
            name = item.get('attribute')
            mapped_item = mapped_attrs.get(name)
            if mapped_item is None:
                mapped_item = next(
                    (candidate for mapped_name, candidate in mapped_attrs.items()
                     if _normalize_attribute_name(mapped_name) == _normalize_attribute_name(name)),
                    None,
                )
            if mapped_item:
                final_attributes.append({
                    'attribute': mapped_item['attribute'],
                    'value': mapped_item['value'],
                    'confidence': mapped_item['confidence'],
                    'source': mapped_item['source'],
                    'shopify_attribute_gid': mapped_item.get('shopify_attribute_gid'),
                    'shopify_value_gid': mapped_item.get('shopify_value_gid'),
                })
                seen.add(name)
            else:
                final_attributes.append({
                    **item,
                    'shopify_attribute_gid': None,
                    'shopify_value_gid': None,
                })

        for name, mapped_item in mapped_attrs.items():
            if name not in seen:
                final_attributes.append({
                    'attribute': mapped_item['attribute'],
                    'value': mapped_item['value'],
                    'confidence': mapped_item['confidence'],
                    'source': mapped_item['source'],
                    'shopify_attribute_gid': mapped_item.get('shopify_attribute_gid'),
                    'shopify_value_gid': mapped_item.get('shopify_value_gid'),
                })

        return final_attributes

    return attributes
