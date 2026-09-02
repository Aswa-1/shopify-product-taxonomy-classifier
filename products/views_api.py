import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Q

from taxonomy.models import TaxonomyCategory
from products.models import Product, ClassificationResult, ProcessingJob
from products.serializers import (
    ProductSerializer, ClassificationResultSerializer,
    ProcessingJobSerializer, TaxonomyCategorySerializer
)
from products.services.excel_importer import import_excel_catalogue
from products.services.classifier import classify_single_product
from products.tasks import trigger_job_processing

logger = logging.getLogger(__name__)

class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.select_related('classification').prefetch_related('images', 'classification__alternatives', 'classification__attributes').all()
    serializer_class = ProductSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(processing_status=status_param.upper())

        requires_review = self.request.query_params.get('requires_review')
        if requires_review is not None:
            val = requires_review.lower() in ('true', '1')
            qs = qs.filter(classification__requires_review=val)

        confidence_lt = self.request.query_params.get('confidence_lt')
        if confidence_lt:
            try:
                val = float(confidence_lt)
                qs = qs.filter(classification__confidence_score__lt=val)
            except ValueError:
                pass

        search_q = self.request.query_params.get('q')
        if search_q:
            qs = qs.filter(
                Q(title__icontains=search_q) |
                Q(product_number__icontains=search_q) |
                Q(model_number__icontains=search_q) |
                Q(product_category__icontains=search_q)
            )

        return qs

    @action(detail=True, methods=['get'])
    def classification(self, request, pk=None):
        product = self.get_object()
        if hasattr(product, 'classification'):
            serializer = ClassificationResultSerializer(product.classification)
            return Response(serializer.data)
        return Response({'detail': 'Classification result not available yet.'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        product = self.get_object()
        if hasattr(product, 'classification'):
            class_res = product.classification
            class_res.user_approved = True
            class_res.requires_review = False
            class_res.save()
            product.processing_status = 'COMPLETED'
            product.save()
            return Response({'status': 'Approved', 'classification_id': class_res.id})
        return Response({'error': 'No classification record to approve.'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def reclassify(self, request, pk=None):
        product = self.get_object()
        class_res = classify_single_product(product, process_images=True)
        if class_res:
            serializer = ClassificationResultSerializer(class_res)
            return Response(serializer.data)
        return Response({'error': 'Reclassification failed.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['patch'])
    def update_classification(self, request, pk=None):
        product = self.get_object()
        if not hasattr(product, 'classification'):
            return Response({'error': 'Product missing classification result.'}, status=status.HTTP_404_NOT_FOUND)

        class_res = product.classification
        cat_id = request.data.get('category_id')
        if cat_id:
            try:
                manual_cat = TaxonomyCategory.objects.get(id=cat_id)
                class_res.manual_category = manual_cat
                class_res.requires_review = False
                class_res.user_approved = True
                class_res.save()
                product.processing_status = 'COMPLETED'
                product.save()
            except TaxonomyCategory.DoesNotExist:
                return Response({'error': 'Invalid category ID.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = ClassificationResultSerializer(class_res)
        return Response(serializer.data)


class ImportViewSet(viewsets.ViewSet):
    parser_classes = (MultiPartParser, FormParser)

    def create(self, request):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({'error': 'No file uploaded.'}, status=status.HTTP_400_BAD_REQUEST)

        if not file_obj.name.endswith('.xlsx'):
            return Response({'error': 'Invalid file format. Please upload an Excel (.xlsx) file.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            job = import_excel_catalogue(file_obj)
            # Trigger asynchronous batch processing
            trigger_job_processing(job.id, batch_size=50, use_celery=False)

            serializer = ProcessingJobSerializer(job)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except Exception as e:
            logger.error(f"Import endpoint failed: {e}", exc_info=True)
            return Response({'error': f'Import failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class JobViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ProcessingJob.objects.all()
    serializer_class = ProcessingJobSerializer

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        job = self.get_object()
        trigger_job_processing(job.id, batch_size=50, use_celery=False)
        serializer = self.get_serializer(job)
        return Response({'status': 'Job processing resumed', 'job': serializer.data})


class TaxonomyViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TaxonomyCategory.objects.all()
    serializer_class = TaxonomyCategorySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        search_q = self.request.query_params.get('q')
        if search_q:
            qs = qs.filter(Q(name__icontains=search_q) | Q(full_path__icontains=search_q))
        return qs
