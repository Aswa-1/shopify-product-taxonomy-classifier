from django.contrib import admin
from products.models import (
    Product, ProductImage, ClassificationResult, 
    ClassificationAlternative, ProductAttribute, ProcessingJob
)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('product_number', 'title', 'product_category', 'processing_status', 'created_at')
    search_fields = ('product_number', 'title', 'model_number')
    list_filter = ('processing_status', 'product_category')

@admin.register(ClassificationResult)
class ClassificationResultAdmin(admin.ModelAdmin):
    list_display = ('product', 'selected_category', 'confidence_score', 'requires_review', 'user_approved')
    list_filter = ('requires_review', 'user_approved', 'model_used')

admin.site.register(ProductImage)
admin.site.register(ClassificationAlternative)
admin.site.register(ProductAttribute)
admin.site.register(ProcessingJob)
