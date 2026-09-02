import pandas as pd
import logging
from django.db import transaction
from products.models import Product, ProductImage, ProcessingJob, ProcessingStatus
from products.services.normalizer import normalize_product_dict

logger = logging.getLogger(__name__)

def import_excel_catalogue(file_path_or_buffer, job_id=None):
    """
    Parses Excel catalogue file, normalizes fields, creates Product and ProductImage DB records,
    and returns the associated ProcessingJob.
    """
    logger.info("Reading Excel catalogue...")
    df = pd.read_excel(file_path_or_buffer)
    total_rows = len(df)

    if job_id:
        job = ProcessingJob.objects.get(id=job_id)
        job.total_products = total_rows
        job.status = ProcessingJob.JobStatus.RUNNING
        job.save()
    else:
        job = ProcessingJob.objects.create(
            status=ProcessingJob.JobStatus.RUNNING,
            total_products=total_rows
        )

    products_to_create = []
    images_map = {} # temp_product_num -> [img_urls]

    # Pre-fetch existing product numbers in DB to avoid collisions or support updates
    existing_product_numbers = set(Product.objects.values_list('product_number', flat=True))

    for idx, row in df.iterrows():
        raw_dict = row.to_dict()
        norm = normalize_product_dict(raw_dict)

        p_num = norm['product_number']
        if not p_num:
            p_num = f"PROD-{idx+1:05d}"
            norm['product_number'] = p_num

        if p_num in existing_product_numbers:
            # Skip existing product numbers for duplicate safety or mark for re-processing
            continue

        prod_obj = Product(
            product_number=p_num,
            model_number=norm['model_number'],
            title=norm['title'],
            description=norm['description'],
            bullets=norm['bullets'],
            product_category=norm['product_category'],
            product_subcategory=norm['product_subcategory'],
            collection_name=norm['collection_name'],
            brand=norm['brand'],
            color=norm['color'],
            materials=norm['materials'],
            dimensions=norm['dimensions'],
            set_includes=norm['set_includes'],
            assembly_required=norm['assembly_required'],
            is_set=norm['is_set'],
            stackable=norm['stackable'],
            country_of_origin=norm['country_of_origin'],
            product_url=norm['product_url'],
            raw_data=norm['raw_data'],
            content_hash=norm['content_hash'],
            job=job,
            processing_status=ProcessingStatus.PENDING
        )
        products_to_create.append(prod_obj)
        images_map[p_num] = norm['images']

    # Bulk create products
    with transaction.atomic():
        if products_to_create:
            Product.objects.bulk_create(products_to_create, batch_size=1000)

        # Retrieve created products to attach ProductImages
        created_products = Product.objects.filter(job=job)
        images_to_create = []
        for p in created_products:
            urls = images_map.get(p.product_number, [])
            for url in urls:
                images_to_create.append(
                    ProductImage(
                        product=p,
                        image_url=url,
                        status=ProductImage.ImageStatus.PENDING
                    )
                )

        if images_to_create:
            ProductImage.objects.bulk_create(images_to_create, batch_size=2000)

    job.total_products = Product.objects.filter(job=job).count()
    job.save()
    logger.info(f"Excel import completed. Created {job.total_products} products for Job #{job.id}.")

    return job
