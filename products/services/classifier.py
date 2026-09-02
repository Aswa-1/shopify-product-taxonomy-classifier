import logging
from django.db import transaction
from products.models import (
    Product, ProductImage, ClassificationResult, 
    ClassificationAlternative, ProductAttribute, ProcessingStatus
)
from products.services.normalizer import normalize_product_dict
from products.services.retrieval import TaxonomyRetrievalService
from products.services.image_processor import process_product_image
from products.services.attribute_extractor import extract_category_attributes
from products.services.confidence import evaluate_classification_confidence

logger = logging.getLogger(__name__)

class ClassificationService:
    def classify(self, product_dict, candidates):
        raise NotImplementedError

class RuleBasedClassifier(ClassificationService):
    def classify(self, product_dict, candidates):
        # Evaluates candidate hierarchy alignment
        return candidates

class HybridClassifier(ClassificationService):
    def classify(self, product_dict, candidates, image_used=False):
        return evaluate_classification_confidence(candidates, product_dict, image_status_used=image_used)


def classify_single_product(product_obj, process_images=True):
    """
    Executes complete classification pipeline for a single Product object:
    1. Normalizes metadata
    2. Processes primary image safely (handles HTTP errors/404/timeouts without throwing)
    3. Retrieves Top candidate taxonomy categories
    4. Evaluates hybrid multi-signal confidence
    5. Extracts category-specific attributes
    6. Saves ClassificationResult, ClassificationAlternatives, ProductAttributes
    7. Updates product processing_status (COMPLETED vs MANUAL_REVIEW vs FAILED)
    """
    try:
        raw_row = product_obj.raw_data if product_obj.raw_data else product_obj
        product_dict = normalize_product_dict(raw_row)

        # Step 1: Image Processing (Safe, non-blocking)
        image_used = False
        if process_images:
            first_image = product_obj.images.filter(status=ProductImage.ImageStatus.PENDING).first()
            if not first_image:
                first_image = product_obj.images.first()
            
            if first_image:
                res = process_product_image(first_image)
                if res.get('success'):
                    image_used = True
                else:
                    logger.info(f"Product #{product_obj.id} image processing fallback to text: {res.get('reason')}")

        # Step 2: Retrieve Top Candidate Categories
        retrieval_service = TaxonomyRetrievalService.get_instance()
        candidates = retrieval_service.retrieve_candidates(product_dict, top_n=10)

        # Step 3: Classification & Confidence Evaluation
        hybrid_classifier = HybridClassifier()
        eval_result = hybrid_classifier.classify(product_dict, candidates, image_used=image_used)

        selected_cat = eval_result['selected_candidate']
        confidence = eval_result['confidence_score']
        requires_review = eval_result['requires_review']
        model_used = eval_result['model_used']
        explanation = eval_result['explanation']

        # Step 4: Attribute Extraction
        extracted_attributes = extract_category_attributes(product_dict, selected_cat)

        # Step 5: Save Classification Database Records atomically
        with transaction.atomic():
            class_res, created = ClassificationResult.objects.update_or_create(
                product=product_obj,
                defaults={
                    'selected_category': selected_cat,
                    'confidence_score': confidence,
                    'status': 'COMPLETED',
                    'image_used': image_used,
                    'model_used': model_used,
                    'explanation': explanation,
                    'requires_review': requires_review,
                }
            )

            # Clear old alternatives & attributes if reclassifying
            class_res.alternatives.all().delete()
            class_res.attributes.all().delete()

            # Save Top Alternatives
            alt_objs = []
            for alt in eval_result['alternatives']:
                alt_objs.append(
                    ClassificationAlternative(
                        classification_result=class_res,
                        category=alt['category'],
                        confidence_score=alt['confidence_score'],
                        rank=alt['rank']
                    )
                )
            if alt_objs:
                ClassificationAlternative.objects.bulk_create(alt_objs)

            # Save Extracted Attributes with Shopify taxonomy metadata when available
            attr_objs = []
            for attr in extracted_attributes:
                product_attr = ProductAttribute(
                    classification_result=class_res,
                    attribute_name=attr['attribute'],
                    attribute_value=attr['value'],
                    confidence_score=attr['confidence'],
                    source=attr['source'],
                    shopify_attribute_gid=attr.get('shopify_attribute_gid'),
                    shopify_value_gid=attr.get('shopify_value_gid'),
                )
                attr_objs.append(product_attr)
            if attr_objs:
                ProductAttribute.objects.bulk_create(attr_objs)

            # Update Product processing status
            if requires_review:
                product_obj.processing_status = ProcessingStatus.MANUAL_REVIEW
            else:
                product_obj.processing_status = ProcessingStatus.COMPLETED

            product_obj.error_message = ""
            product_obj.save()

        return class_res

    except Exception as e:
        logger.error(f"Error classifying product #{product_obj.id}: {e}", exc_info=True)
        product_obj.processing_status = ProcessingStatus.FAILED
        product_obj.error_message = str(e)
        product_obj.save()
        return None
