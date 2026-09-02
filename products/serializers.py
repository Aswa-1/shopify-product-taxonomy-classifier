from rest_framework import serializers
from taxonomy.models import TaxonomyCategory, TaxonomyAttribute
from products.models import (
    Product, ProductImage, ClassificationResult, 
    ClassificationAlternative, ProductAttribute, ProcessingJob
)

class TaxonomyCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxonomyCategory
        fields = ['id', 'shopify_id', 'gid', 'name', 'full_path', 'level', 'parent_id']


class TaxonomyAttributeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxonomyAttribute
        fields = ['id', 'gid', 'name', 'value_type']


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ['id', 'image_url', 'local_path', 'status', 'http_status', 'error_message', 'processed']


class ProductAttributeSerializer(serializers.ModelSerializer):
    confidence = serializers.SerializerMethodField()

    class Meta:
        model = ProductAttribute
        fields = [
            'id', 'attribute_name', 'attribute_value',
            'shopify_attribute_gid', 'shopify_value_gid',
            'confidence_score', 'confidence', 'source'
        ]

    def get_confidence(self, obj):
        return obj.confidence_score


class ClassificationAlternativeSerializer(serializers.ModelSerializer):
    category = TaxonomyCategorySerializer(read_only=True)
    
    class Meta:
        model = ClassificationAlternative
        fields = ['id', 'category', 'confidence_score', 'rank']


class ClassificationResultSerializer(serializers.ModelSerializer):
    selected_category = TaxonomyCategorySerializer(read_only=True)
    manual_category = TaxonomyCategorySerializer(read_only=True)
    effective_category_name = serializers.SerializerMethodField()
    alternatives = ClassificationAlternativeSerializer(many=True, read_only=True)
    attributes = ProductAttributeSerializer(many=True, read_only=True)

    class Meta:
        model = ClassificationResult
        fields = [
            'id', 'selected_category', 'manual_category', 'effective_category_name',
            'confidence_score', 'status', 'image_used', 'model_used', 'explanation',
            'requires_review', 'user_approved', 'alternatives', 'attributes',
            'created_at', 'updated_at'
        ]

    def get_effective_category_name(self, obj):
        cat = obj.get_effective_category()
        return cat.full_path if cat else None


class ProductSerializer(serializers.ModelSerializer):
    images = ProductImageSerializer(many=True, read_only=True)
    classification = ClassificationResultSerializer(read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'product_number', 'model_number', 'title', 'description', 'bullets',
            'product_category', 'product_subcategory', 'collection_name', 'brand',
            'color', 'materials', 'dimensions', 'set_includes', 'assembly_required',
            'is_set', 'stackable', 'country_of_origin', 'product_url',
            'processing_status', 'error_message', 'images', 'classification',
            'created_at', 'updated_at'
        ]


class ProcessingJobSerializer(serializers.ModelSerializer):
    progress_percentage = serializers.SerializerMethodField()

    class Meta:
        model = ProcessingJob
        fields = [
            'id', 'status', 'total_products', 'processed_products',
            'successful_products', 'failed_products', 'manual_review_products',
            'error_count', 'progress_percentage', 'started_at', 'completed_at',
            'created_at', 'updated_at'
        ]

    def get_progress_percentage(self, obj):
        if obj.total_products > 0:
            return round((obj.processed_products / obj.total_products) * 100, 1)
        return 0.0
