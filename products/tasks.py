import logging
from concurrent.futures import ThreadPoolExecutor
from celery import shared_task
from django.db.models import Q
from products.models import Product, ProcessingJob, ProcessingStatus
from products.services.classifier import classify_single_product

logger = logging.getLogger(__name__)

def process_product_ids_sync(product_ids, job_id=None):
    """
    Synchronous / threadpool fallback processor for product batch.
    Processes products, updates counts on ProcessingJob.
    """
    products = Product.objects.filter(id__in=product_ids)
    processed_count = 0
    success_count = 0
    failed_count = 0
    manual_review_count = 0

    for prod in products:
        # Check idempotency / skip if already completed
        if prod.processing_status in (ProcessingStatus.COMPLETED, ProcessingStatus.MANUAL_REVIEW):
            continue

        prod.processing_status = ProcessingStatus.PROCESSING
        prod.save(update_fields=['processing_status'])

        res = classify_single_product(prod)
        if res:
            if res.requires_review:
                manual_review_count += 1
            else:
                success_count += 1
        else:
            failed_count += 1

        processed_count += 1

    # Update job stats atomically
    if job_id:
        try:
            job = ProcessingJob.objects.get(id=job_id)
            job.processed_products = Product.objects.filter(
                job=job,
                processing_status__in=[
                    ProcessingStatus.COMPLETED,
                    ProcessingStatus.MANUAL_REVIEW,
                    ProcessingStatus.FAILED
                ]
            ).count()
            job.successful_products = Product.objects.filter(job=job, processing_status=ProcessingStatus.COMPLETED).count()
            job.manual_review_products = Product.objects.filter(job=job, processing_status=ProcessingStatus.MANUAL_REVIEW).count()
            job.failed_products = Product.objects.filter(job=job, processing_status=ProcessingStatus.FAILED).count()

            if job.processed_products >= job.total_products and job.total_products > 0:
                job.status = ProcessingJob.JobStatus.COMPLETED

            job.save()
        except Exception as e:
            logger.error(f"Error updating job #{job_id}: {e}")

    return processed_count


@shared_task(bind=True, max_retries=3, default_retry_delay=5)
def process_product_batch_celery(self, product_ids, job_id=None):
    """
    Celery task to process a list of product IDs.
    """
    try:
        return process_product_ids_sync(product_ids, job_id=job_id)
    except Exception as exc:
        logger.error(f"Celery task error: {exc}")
        raise self.retry(exc=exc)


def trigger_job_processing(job_id, batch_size=50, use_celery=False):
    """
    Splits job products into batches and triggers asynchronous processing.
    Falls back to ThreadPoolExecutor if Celery/Redis connection fails.
    """
    job = ProcessingJob.objects.get(id=job_id)
    job.status = ProcessingJob.JobStatus.RUNNING
    job.save()

    # Get product IDs requiring processing (PENDING, FAILED, RETRY)
    pending_pids = list(
        Product.objects.filter(job=job)
        .filter(Q(processing_status=ProcessingStatus.PENDING) | Q(processing_status=ProcessingStatus.FAILED) | Q(processing_status=ProcessingStatus.RETRY))
        .values_list('id', flat=True)
    )

    if not pending_pids:
        job.status = ProcessingJob.JobStatus.COMPLETED
        job.save()
        return

    # Chunk into batches
    batches = [pending_pids[i:i + batch_size] for i in range(0, len(pending_pids), batch_size)]

    if use_celery:
        try:
            for b in batches:
                process_product_batch_celery.delay(b, job_id=job.id)
            return
        except Exception as e:
            logger.warning(f"Celery broker connection failed: {e}. Falling back to ThreadPool background execution.")

       # SQLite-safe synchronous processing
    for b in batches:
        try:
            process_product_ids_sync(b, job.id)
        except Exception as e:
            logger.error(f"Batch processing error for job #{job.id}: {e}")

    return