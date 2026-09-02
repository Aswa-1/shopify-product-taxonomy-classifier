import tempfile
from pathlib import Path

from django.test import TestCase

from taxonomy.importer import import_shopify_attribute_values, parse_attribute_value_line
from taxonomy.models import TaxonomyAttribute, TaxonomyAttributeValue, TaxonomyCategory
from products.models import Product, ClassificationResult, ProductAttribute
from products.services.attribute_extractor import (
    _taxonomy_value_lookup_cache,
    extract_category_attributes,
    refresh_product_attribute_mappings,
)


class TaxonomyTestCase(TestCase):
    def setUp(self):
        _taxonomy_value_lookup_cache.clear()
        self.parent = TaxonomyCategory.objects.create(
            shopify_id='furn-1',
            gid='gid://shopify/TaxonomyCategory/furn-1',
            name='Furniture',
            full_path='Furniture',
            level=1
        )
        self.child = TaxonomyCategory.objects.create(
            shopify_id='furn-2',
            gid='gid://shopify/TaxonomyCategory/furn-2',
            name='Sofas',
            full_path='Furniture > Sofas',
            parent=self.parent,
            level=2
        )

    def test_taxonomy_hierarchy(self):
        self.assertEqual(self.child.parent, self.parent)
        self.assertEqual(self.parent.children.count(), 1)
        self.assertEqual(self.child.level, 2)
        self.assertEqual(str(self.child), 'Furniture > Sofas')

    def test_taxonomy_attribute(self):
        attr = TaxonomyAttribute.objects.create(
            category=self.child,
            name='Material',
            value_type='string'
        )
        self.assertEqual(attr.category, self.child)
        self.assertEqual(self.child.attributes.count(), 1)

    def test_parse_valid_line(self):
        parsed = parse_attribute_value_line('gid://shopify/TaxonomyValue/50818 : #1 [Fishing hook size]')
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['gid'], 'gid://shopify/TaxonomyValue/50818')
        self.assertEqual(parsed['value'], '#1')
        self.assertEqual(parsed['attribute_name'], 'Fishing hook size')

    def test_parse_invalid_lines(self):
        self.assertIsNone(parse_attribute_value_line(''))
        self.assertIsNone(parse_attribute_value_line('not a valid line'))
        self.assertIsNone(parse_attribute_value_line('gid://shopify/TaxonomyValue/50818 : #1'))

    def test_import_taxonomy_value(self):
        attr = TaxonomyAttribute.objects.create(
            category=self.child,
            name='Fishing hook size',
            value_type='string'
        )

        with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as fh:
            fh.write('gid://shopify/TaxonomyValue/50818 : #1 [Fishing hook size]\n')
            temp_path = Path(fh.name)

        try:
            result = import_shopify_attribute_values(temp_path)
            self.assertEqual(result['successfully_imported'], 1)
            self.assertEqual(result['skipped'], 0)
            self.assertTrue(
                TaxonomyAttributeValue.objects.filter(
                    attribute=attr,
                    gid='gid://shopify/TaxonomyValue/50818',
                    value='#1',
                    normalized_value='#1'
                ).exists()
            )
        finally:
            temp_path.unlink(missing_ok=True)

    def test_import_matches_correct_taxonomy_attribute(self):
        fishing_attr = TaxonomyAttribute.objects.create(
            category=self.child,
            name='Fishing hook size',
            value_type='string'
        )
        color_attr = TaxonomyAttribute.objects.create(
            category=self.child,
            name='Color',
            value_type='string'
        )

        with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as fh:
            fh.write('gid://shopify/TaxonomyValue/11111 : Red [Color]\n')
            fh.write('gid://shopify/TaxonomyValue/50818 : #1 [Fishing hook size]\n')
            temp_path = Path(fh.name)

        try:
            result = import_shopify_attribute_values(temp_path)
            self.assertEqual(result['successfully_imported'], 2)
            self.assertTrue(TaxonomyAttributeValue.objects.filter(attribute=fishing_attr, gid='gid://shopify/TaxonomyValue/50818').exists())
            self.assertTrue(TaxonomyAttributeValue.objects.filter(attribute=color_attr, gid='gid://shopify/TaxonomyValue/11111').exists())
        finally:
            temp_path.unlink(missing_ok=True)

    def test_import_duplicate_handling(self):
        attr = TaxonomyAttribute.objects.create(
            category=self.child,
            name='Fishing hook size',
            value_type='string'
        )
        TaxonomyAttributeValue.objects.create(
            attribute=attr,
            gid='gid://shopify/TaxonomyValue/50818',
            value='#1',
            normalized_value='#1'
        )

        with tempfile.NamedTemporaryFile('w', encoding='utf-8', delete=False) as fh:
            fh.write('gid://shopify/TaxonomyValue/50818 : #1 [Fishing hook size]\n')
            temp_path = Path(fh.name)

        try:
            result = import_shopify_attribute_values(temp_path)
            self.assertEqual(result['successfully_imported'], 0)
            self.assertEqual(result['skipped'], 1)
        finally:
            temp_path.unlink(missing_ok=True)

    def test_exact_source_value_maps_to_shopify_taxonomy_value(self):
        color_attr = TaxonomyAttribute.objects.create(category=self.child, name='Color', value_type='string', gid='gid://shopify/TaxonomyAttribute/color')
        TaxonomyAttributeValue.objects.create(
            attribute=color_attr,
            gid='gid://shopify/TaxonomyValue/11111',
            value='Red',
            normalized_value='red',
        )

        mapped = extract_category_attributes({'color': 'Red'}, self.child)
        self.assertTrue(mapped)
        self.assertEqual(mapped[0]['attribute'], 'Color')
        self.assertEqual(mapped[0]['shopify_attribute_gid'], 'gid://shopify/TaxonomyAttribute/color')
        self.assertEqual(mapped[0]['shopify_value_gid'], 'gid://shopify/TaxonomyValue/11111')
        self.assertEqual(mapped[0]['source'], 'Source Data → Shopify Taxonomy Mapping')

    def test_unmapped_value_keeps_source_data_and_null_gid(self):
        TaxonomyAttribute.objects.create(category=self.child, name='Color', value_type='string', gid='gid://shopify/TaxonomyAttribute/color')
        mapped = extract_category_attributes({'color': 'Chartreuse'}, self.child)
        self.assertEqual(len(mapped), 1)
        self.assertEqual(mapped[0]['attribute'], 'Color')
        self.assertEqual(mapped[0]['attribute_value'] if 'attribute_value' in mapped[0] else mapped[0]['value'], 'Chartreuse')
        self.assertIsNone(mapped[0].get('shopify_value_gid'))
        self.assertIsNone(mapped[0].get('shopify_attribute_gid'))

    def test_relevant_category_attributes_are_limited_to_current_category_hierarchy(self):
        unrelated = TaxonomyAttribute.objects.create(category=self.child, name='Fishing hook size', value_type='string', gid='gid://shopify/TaxonomyAttribute/fishing')
        TaxonomyAttributeValue.objects.create(attribute=unrelated, gid='gid://shopify/TaxonomyValue/50818', value='#1', normalized_value='#1')

        color_attr = TaxonomyAttribute.objects.create(category=self.child, name='Color', value_type='string', gid='gid://shopify/TaxonomyAttribute/color')
        TaxonomyAttributeValue.objects.create(attribute=color_attr, gid='gid://shopify/TaxonomyValue/11111', value='Red', normalized_value='red')

        product_attrs = extract_category_attributes({'color': 'Red'}, self.child)
        names = {attr['attribute'] for attr in product_attrs}
        self.assertIn('Color', names)
        self.assertNotIn('Fishing hook size', names)

    def test_refresh_existing_product_attribute_rows_updates_shopify_gids(self):
        color_attr = TaxonomyAttribute.objects.create(category=self.child, name='Color', value_type='string', gid='gid://shopify/TaxonomyAttribute/color')
        TaxonomyAttributeValue.objects.create(attribute=color_attr, gid='gid://shopify/TaxonomyValue/11111', value='Red', normalized_value='red')

        product = Product.objects.create(
            product_number='SKU-100',
            title='Red Sofa',
            description='A red sofa',
            color='Red',
            product_category='Furniture',
            product_subcategory='Sofas'
        )
        classification = ClassificationResult.objects.create(
            product=product,
            selected_category=self.child,
            confidence_score=0.9,
        )
        ProductAttribute.objects.create(
            classification_result=classification,
            attribute_name='Color',
            attribute_value='Red',
            confidence_score=1.0,
            source='Source Data',
            shopify_attribute_gid=None,
            shopify_value_gid=None,
        )

        result = refresh_product_attribute_mappings(product)

        self.assertEqual(result['updated'], 1)
        self.assertEqual(result['mapped'], 1)

        attr = classification.attributes.get(attribute_name='Color')
        self.assertEqual(attr.shopify_attribute_gid, 'gid://shopify/TaxonomyAttribute/color')
        self.assertEqual(attr.shopify_value_gid, 'gid://shopify/TaxonomyValue/11111')
        self.assertEqual(attr.source, 'Source Data → Shopify Taxonomy Mapping')
