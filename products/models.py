from django.db import models
from taxonomy.models import TaxonomyCategory

class ProcessingStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    PROCESSING = 'PROCESSING', 'Processing'
    COMPLETED = 'COMPLETED', 'Completed'
    FAILED = 'FAILED', 'Failed'
    RETRY = 'RETRY', 'Retry'
    MANUAL_REVIEW = 'MANUAL_REVIEW', 'Manual Review'


class ProcessingJob(models.Model):
    class JobStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        RUNNING = 'RUNNING', 'Running'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'
        PAUSED = 'PAUSED', 'Paused'

    status = models.CharField(
        max_length=20,
        choices=JobStatus.choices,
        default=JobStatus.PENDING,
        db_index=True
    )
    total_products = models.IntegerField(default=0)
    processed_products = models.IntegerField(default=0)
    successful_products = models.IntegerField(default=0)
    failed_products = models.IntegerField(default=0)
    manual_review_products = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Job #{self.id} - {self.status} ({self.processed_products}/{self.total_products})"


class Product(models.Model):
    product_number = models.CharField(max_length=100, db_index=True)
    model_number = models.CharField(max_length=100, blank=True, db_index=True)
    title = models.CharField(max_length=500, db_index=True)
    description = models.TextField(blank=True)
    bullets = models.TextField(blank=True)
    product_category = models.CharField(max_length=255, blank=True, db_index=True)
    product_subcategory = models.CharField(max_length=255, blank=True, db_index=True)
    collection_name = models.CharField(max_length=255, blank=True)
    brand = models.CharField(max_length=255, blank=True)
    color = models.CharField(max_length=255, blank=True)
    materials = models.CharField(max_length=500, blank=True)
    dimensions = models.CharField(max_length=500, blank=True)
    set_includes = models.TextField(blank=True)
    assembly_required = models.CharField(max_length=50, blank=True)
    is_set = models.CharField(max_length=50, blank=True)
    stackable = models.CharField(max_length=50, blank=True)
    country_of_origin = models.CharField(max_length=255, blank=True)
    product_url = models.CharField(max_length=1000, blank=True)
    
    raw_data = models.JSONField(default=dict, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, db_index=True)
    job = models.ForeignKey(
        ProcessingJob,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='products'
    )
    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        db_index=True
    )
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['id']
        indexes = [
            models.Index(fields=['product_number']),
            models.Index(fields=['model_number']),
            models.Index(fields=['processing_status']),
            models.Index(fields=['content_hash']),
        ]

    def __str__(self):
        return f"[{self.product_number}] {self.title}"


class ProductImage(models.Model):
    class ImageStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        SUCCESS = 'SUCCESS', 'Success'
        FAILED = 'FAILED', 'Failed'

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image_url = models.URLField(max_length=1000)
    local_path = models.CharField(max_length=500, blank=True)
    status = models.CharField(
        max_length=20,
        choices=ImageStatus.choices,
        default=ImageStatus.PENDING
    )
    http_status = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    processed = models.BooleanField(default=False)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"Image for {self.product.product_number}: {self.status}"


class ClassificationResult(models.Model):
    product = models.OneToOneField(Product, on_delete=models.CASCADE, related_name='classification')
    selected_category = models.ForeignKey(
        TaxonomyCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='classifications'
    )
    confidence_score = models.FloatField(default=0.0, db_index=True)
    status = models.CharField(max_length=50, default='COMPLETED')
    image_used = models.BooleanField(default=False)
    model_used = models.CharField(max_length=100, default='Demo Mode (Rule + TF-IDF)')
    explanation = models.TextField(blank=True)
    requires_review = models.BooleanField(default=False, db_index=True)
    user_approved = models.BooleanField(default=False, db_index=True)
    manual_category = models.ForeignKey(
        TaxonomyCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='manual_classifications'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['requires_review']),
            models.Index(fields=['confidence_score']),
            models.Index(fields=['user_approved']),
        ]

    def get_effective_category(self):
        return self.manual_category or self.selected_category

    def __str__(self):
        cat_name = self.get_effective_category().full_path if self.get_effective_category() else "Unclassified"
        return f"{self.product.product_number} -> {cat_name} ({self.confidence_score:.2f})"


class ClassificationAlternative(models.Model):
    classification_result = models.ForeignKey(
        ClassificationResult,
        on_delete=models.CASCADE,
        related_name='alternatives'
    )
    category = models.ForeignKey(TaxonomyCategory, on_delete=models.CASCADE)
    confidence_score = models.FloatField()
    rank = models.IntegerField()

    class Meta:
        ordering = ['rank']

    def __str__(self):
        return f"Rank {self.rank}: {self.category.name} ({self.confidence_score:.2f})"


class ProductAttribute(models.Model):
    classification_result = models.ForeignKey(
        ClassificationResult,
        on_delete=models.CASCADE,
        related_name='attributes'
    )
    attribute_name = models.CharField(max_length=255)
    attribute_value = models.CharField(max_length=500)
    confidence_score = models.FloatField(default=1.0)
    source = models.CharField(max_length=100, default='Extracted')
    shopify_attribute_gid = models.CharField(max_length=200, blank=True, null=True, db_index=True)
    shopify_value_gid = models.CharField(max_length=200, blank=True, null=True, db_index=True)

    class Meta:
        ordering = ['attribute_name']
        indexes = [
            models.Index(fields=['shopify_attribute_gid']),
            models.Index(fields=['shopify_value_gid']),
        ]

    def __str__(self):
        return f"{self.attribute_name}: {self.attribute_value}"
