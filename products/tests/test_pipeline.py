from django.test import TestCase
from taxonomy.models import TaxonomyCategory
from products.models import (
    Product, ProductImage, ClassificationResult, 
    ProcessingJob, ProcessingStatus
)
from products.services.normalizer import clean_text, normalize_product_dict
from products.services.classifier import classify_single_product
from products.services.image_processor import process_product_image
from products.services.retrieval import TaxonomyRetrievalService
from products.tasks import process_product_ids_sync, trigger_job_processing

class ClassificationPipelineTestCase(TestCase):
    def setUp(self):
        # Create dummy Taxonomy Categories
        self.cat_sofa = TaxonomyCategory.objects.create(
            shopify_id='sofa-101',
            gid='gid://shopify/TaxonomyCategory/sofa-101',
            name='Sofas',
            full_path='Furniture > Sofas',
            level=2
        )
        self.cat_armchair = TaxonomyCategory.objects.create(
            shopify_id='chair-102',
            gid='gid://shopify/TaxonomyCategory/chair-102',
            name='Armchairs',
            full_path='Furniture > Chairs > Armchairs, Recliners & Sleeper Chairs > Armchairs',
            level=4
        )
        self.cat_pencil_holder = TaxonomyCategory.objects.create(
            shopify_id='off-103',
            gid='gid://shopify/TaxonomyCategory/off-103',
            name='Pencil Holders',
            full_path='Office Supplies > Desk Accessories > Pencil Holders',
            level=3
        )
        self.cat_ottoman = TaxonomyCategory.objects.create(
            shopify_id='furn-104',
            gid='gid://shopify/TaxonomyCategory/furn-104',
            name='Ottomans',
            full_path='Furniture > Ottomans',
            level=2
        )

    def test_text_normalization(self):
        dirty_html = "<p>Modern Velvet Sofa</p><br>_x000D_\n  Deeply tufted.  "
        cleaned = clean_text(dirty_html)
        self.assertEqual(cleaned, "Modern Velvet Sofa Deeply tufted.")

    def test_confidence_calibration(self):
        TaxonomyRetrievalService.get_instance().initialize(force=True)
        
        # A. Strong Evidence: Title + Category + Description + Materials agree
        p_strong = Product.objects.create(
            product_number='CALIB-01',
            title='Empress Upholstered Fabric Armchair by Modway',
            description='End the rule of unjust sovereignties. Plush cushion armchair.',
            product_category='Furniture',
            product_subcategory='Armchairs',
            materials='Fabric Wood'
        )
        res_strong = classify_single_product(p_strong, process_images=False)
        self.assertGreaterEqual(res_strong.confidence_score, 0.80)
        self.assertFalse(res_strong.requires_review)

        # B. Moderate Evidence: Title available, missing description and materials
        p_mod = Product.objects.create(
            product_number='CALIB-02',
            title='Modern Velvet Living Room Sofa',
            description='',
            product_category='Furniture',
            materials=''
        )
        res_mod = classify_single_product(p_mod, process_images=False)
        self.assertGreaterEqual(res_mod.confidence_score, 0.60)
        self.assertLess(res_mod.confidence_score, 0.85)

        # C. Weak Evidence: Generic title only
        p_weak = Product.objects.create(
            product_number='CALIB-03',
            title='Modern Product Item',
            description='',
            product_category=''
        )
        res_weak = classify_single_product(p_weak, process_images=False)
        self.assertLess(res_weak.confidence_score, 0.60)
        self.assertTrue(res_weak.requires_review)

    def test_armchair_quality_classification_regression(self):
        TaxonomyRetrievalService.get_instance().initialize(force=True)
        prod = Product.objects.create(
            product_number='QUAL-01',
            title='Empress Upholstered Fabric Armchair by Modway',
            description='A plush fabric armchair.',
            product_category='Living Room',
            product_subcategory='Armchairs',
            materials='Fabric Wood'
        )
        res = classify_single_product(prod, process_images=False)
        self.assertIsNotNone(res)
        self.assertEqual(res.selected_category, self.cat_armchair)
        self.assertGreaterEqual(res.confidence_score, 0.80)

    def test_pencil_holder_quality_classification_regression(self):
        TaxonomyRetrievalService.get_instance().initialize(force=True)
        prod = Product.objects.create(
            product_number='QUAL-02',
            title='Lava Pencil Holder by Modway',
            description='Sleek pencil holder for desk.',
            product_category='Office Supplies',
            product_subcategory='Pencil Holders',
            materials='Plastic'
        )
        res = classify_single_product(prod, process_images=False)
        self.assertIsNotNone(res)
        self.assertEqual(res.selected_category, self.cat_pencil_holder)
        self.assertGreaterEqual(res.confidence_score, 0.80)

    def test_ottoman_quality_classification_regression(self):
        TaxonomyRetrievalService.get_instance().initialize(force=True)
        prod = Product.objects.create(
            product_number='QUAL-03',
            title='Volt Storage Upholstered Vinyl Ottoman by Modway',
            product_category='Furniture',
            product_subcategory='Ottomans'
        )
        res = classify_single_product(prod, process_images=False)
        self.assertIsNotNone(res)
        self.assertEqual(res.selected_category, self.cat_ottoman)

    def test_missing_description_classification(self):
        TaxonomyRetrievalService.get_instance().initialize(force=True)
        prod = Product.objects.create(
            product_number='TEST-001',
            title='Modern Velvet Living Room Sofa',
            description='',
            product_category='Living Room',
            product_subcategory='Sofas',
            materials='Velvet'
        )
        res = classify_single_product(prod, process_images=False)
        self.assertIsNotNone(res)
        self.assertEqual(res.selected_category, self.cat_sofa)
        self.assertGreaterEqual(res.confidence_score, 0.30)

    def test_missing_image_classification(self):
        TaxonomyRetrievalService.get_instance().initialize(force=True)
        prod = Product.objects.create(
            product_number='TEST-002',
            title='Empress Leather Armchair',
            description='A luxurious armchair for living room.',
            product_category='Living Room',
            product_subcategory='Armchairs'
        )
        res = classify_single_product(prod, process_images=True)
        self.assertIsNotNone(res)
        self.assertFalse(res.image_used)

    def test_broken_image_url_handling(self):
        TaxonomyRetrievalService.get_instance().initialize(force=True)
        prod = Product.objects.create(
            product_number='TEST-003',
            title='Broken Image Velvet Sofa',
            description='Test sofa with broken image link.',
            product_category='Living Room'
        )
        img = ProductImage.objects.create(
            product=prod,
            image_url='https://invalid.domain.example.com/nonexistent_image.jpg',
            status=ProductImage.ImageStatus.PENDING
        )
        img_res = process_product_image(img)
        self.assertFalse(img_res['success'])
        self.assertEqual(img.status, ProductImage.ImageStatus.FAILED)

        res = classify_single_product(prod, process_images=True)
        self.assertIsNotNone(res)
        self.assertFalse(res.image_used)

    def test_low_confidence_and_alternatives(self):
        TaxonomyRetrievalService.get_instance().initialize(force=True)
        prod = Product.objects.create(
            product_number='TEST-004',
            title='Random Ambiguous Utility Item',
            description='Unrelated text without clear furniture signal.',
            product_category='General Items'
        )
        res = classify_single_product(prod, process_images=False)
        self.assertIsNotNone(res)
        self.assertTrue(res.requires_review)
        self.assertEqual(prod.processing_status, ProcessingStatus.MANUAL_REVIEW)

    def test_batch_processing_and_resumability(self):
        job = ProcessingJob.objects.create(total_products=3, status=ProcessingJob.JobStatus.RUNNING)
        p1 = Product.objects.create(product_number='B1', title='Sofa 1', job=job)
        p2 = Product.objects.create(product_number='B2', title='Sofa 2', job=job)
        p3 = Product.objects.create(product_number='B3', title='Sofa 3', job=job)

        process_product_ids_sync([p1.id], job.id)
        p1.refresh_from_db()
        self.assertIn(p1.processing_status, [ProcessingStatus.COMPLETED, ProcessingStatus.MANUAL_REVIEW])

        process_product_ids_sync([p2.id, p3.id], job.id)
        job.refresh_from_db()
        self.assertEqual(job.processed_products, 3)
