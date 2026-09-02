from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.db.models import Count, Q
from products.models import Product, ClassificationResult, ProcessingJob, ProcessingStatus
from taxonomy.models import TaxonomyCategory

def dashboard_view(request):
    total_products = Product.objects.count()
    processed_count = Product.objects.filter(processing_status__in=[ProcessingStatus.COMPLETED, ProcessingStatus.MANUAL_REVIEW]).count()
    pending_count = Product.objects.filter(processing_status=ProcessingStatus.PENDING).count()
    failed_count = Product.objects.filter(processing_status=ProcessingStatus.FAILED).count()
    manual_review_count = Product.objects.filter(classification__requires_review=True, classification__user_approved=False).count()

    high_conf_count = ClassificationResult.objects.filter(confidence_score__gte=0.80).count()
    med_conf_count = ClassificationResult.objects.filter(confidence_score__gte=0.60, confidence_score__lt=0.80).count()
    low_conf_count = ClassificationResult.objects.filter(confidence_score__lt=0.60).count()

    active_job = ProcessingJob.objects.filter(status=ProcessingJob.JobStatus.RUNNING).first()
    recent_jobs = ProcessingJob.objects.all()[:5]

    context = {
        'total_products': total_products,
        'processed_count': processed_count,
        'pending_count': pending_count,
        'failed_count': failed_count,
        'manual_review_count': manual_review_count,
        'high_conf_count': high_conf_count,
        'med_conf_count': med_conf_count,
        'low_conf_count': low_conf_count,
        'active_job': active_job,
        'recent_jobs': recent_jobs,
    }
    return render(request, 'dashboard.html', context)


def products_list_view(request):
    qs = Product.objects.select_related('classification', 'classification__selected_category', 'classification__manual_category').prefetch_related('images').all()

    search_q = request.GET.get('q', '').strip()
    if search_q:
        qs = qs.filter(
            Q(title__icontains=search_q) |
            Q(product_number__icontains=search_q) |
            Q(model_number__icontains=search_q) |
            Q(product_category__icontains=search_q)
        )

    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        qs = qs.filter(processing_status=status_filter.upper())

    review_filter = request.GET.get('requires_review', '').strip()
    if review_filter.lower() in ('true', '1'):
        qs = qs.filter(classification__requires_review=True, classification__user_approved=False)

    confidence_filter = request.GET.get('confidence', '').strip()
    if confidence_filter == 'high':
        qs = qs.filter(classification__confidence_score__gte=0.80)
    elif confidence_filter == 'medium':
        qs = qs.filter(classification__confidence_score__gte=0.60, classification__confidence_score__lt=0.80)
    elif confidence_filter == 'low':
        qs = qs.filter(classification__confidence_score__lt=0.60)

    paginator = Paginator(qs, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search_q': search_q,
        'status_filter': status_filter,
        'review_filter': review_filter,
        'confidence_filter': confidence_filter,
    }
    return render(request, 'products_list.html', context)


def product_detail_view(request, pk):
    product = get_object_or_404(
        Product.objects.select_related(
            'classification',
            'classification__selected_category',
            'classification__manual_category'
        ).prefetch_related(
            'images',
            'classification__alternatives',
            'classification__alternatives__category',
            'classification__attributes'
        ),
        pk=pk
    )

    all_categories = TaxonomyCategory.objects.order_by('full_path')[:500] # Top choices for dropdown modal

    context = {
        'product': product,
        'classification': getattr(product, 'classification', None),
        'all_categories': all_categories,
    }
    return render(request, 'product_detail.html', context)


def review_queue_view(request):
    qs = Product.objects.filter(
        classification__requires_review=True,
        classification__user_approved=False
    ).select_related('classification', 'classification__selected_category').prefetch_related('images', 'classification__alternatives')

    paginator = Paginator(qs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
    }
    return render(request, 'review_queue.html', context)


def import_upload_view(request):
    active_job = ProcessingJob.objects.filter(status=ProcessingJob.JobStatus.RUNNING).first()
    recent_jobs = ProcessingJob.objects.all()[:5]

    context = {
        'active_job': active_job,
        'recent_jobs': recent_jobs,
    }
    return render(request, 'import.html', context)
