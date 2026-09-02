from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from taxonomy.models import TaxonomyCategory
from products.models import Product, ClassificationResult, ProcessingJob, ProcessingStatus

class APIEndpointsTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.category = TaxonomyCategory.objects.create(
            shopify_id='api-cat-1',
            name='Armchairs',
            full_path='Furniture > Armchairs'
        )
        self.product = Product.objects.create(
            product_number='API-001',
            title='API Test Armchair',
            product_category='Furniture'
        )
        self.classification = ClassificationResult.objects.create(
            product=self.product,
            selected_category=self.category,
            confidence_score=0.55,
            requires_review=True
        )

    def test_product_list_api(self):
        response = self.client.get('/api/products/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

    def test_product_detail_api(self):
        response = self.client.get(f'/api/products/{self.product.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['product_number'], 'API-001')

    def test_product_classification_api(self):
        response = self.client.get(f'/api/products/{self.product.id}/classification/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['confidence_score'], 0.55)

    def test_approve_classification_api(self):
        response = self.client.post(f'/api/products/{self.product.id}/approve/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.product.refresh_from_db()
        self.assertEqual(self.product.processing_status, ProcessingStatus.COMPLETED)

    def test_update_classification_api(self):
        new_cat = TaxonomyCategory.objects.create(
            shopify_id='api-cat-2',
            name='Sofas',
            full_path='Furniture > Sofas'
        )
        response = self.client.patch(
            f'/api/products/{self.product.id}/update_classification/',
            {'category_id': new_cat.id},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.classification.refresh_from_db()
        self.assertEqual(self.classification.manual_category, new_cat)

    def test_job_resume_api(self):
        job = ProcessingJob.objects.create(total_products=5, status=ProcessingJob.JobStatus.PAUSED)
        Product.objects.create(product_number='RESUME-01', title='Pending Resume Product', job=job, processing_status=ProcessingStatus.PENDING)
        response = self.client.post(f'/api/jobs/{job.id}/resume/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        job.refresh_from_db()
        self.assertIn(job.status, [ProcessingJob.JobStatus.RUNNING, ProcessingJob.JobStatus.COMPLETED])
