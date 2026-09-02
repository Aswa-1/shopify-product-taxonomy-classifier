import io
import requests
import logging
from PIL import Image
from products.models import ProductImage

logger = logging.getLogger(__name__)

def process_product_image(product_image_obj):
    """
    Safely downloads and validates a ProductImage instance.
    Handles HTTP errors, timeouts, invalid images, corrupted formats without raising exceptions.
    Updates the ProductImage record status, http_status, and error_message.
    """
    url = product_image_obj.image_url
    if not url or not url.startswith('http'):
        product_image_obj.status = ProductImage.ImageStatus.FAILED
        product_image_obj.error_message = "Invalid URL schema"
        product_image_obj.processed = True
        product_image_obj.save()
        return {'success': False, 'reason': 'Invalid URL'}

    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=3.5, stream=True)
        product_image_obj.http_status = response.status_code

        if response.status_code != 200:
            product_image_obj.status = ProductImage.ImageStatus.FAILED
            product_image_obj.error_message = f"HTTP Error {response.status_code}"
            product_image_obj.processed = True
            product_image_obj.save()
            return {'success': False, 'reason': f"HTTP {response.status_code}"}

        # Validate image content with Pillow
        image_bytes = response.content
        img = Image.open(io.BytesIO(image_bytes))
        img.verify() # Verify file integrity

        product_image_obj.status = ProductImage.ImageStatus.SUCCESS
        product_image_obj.error_message = ""
        product_image_obj.processed = True
        product_image_obj.save()

        return {
            'success': True,
            'format': img.format,
            'size': img.size,
            'bytes': len(image_bytes)
        }

    except requests.exceptions.Timeout:
        product_image_obj.status = ProductImage.ImageStatus.FAILED
        product_image_obj.error_message = "Connection Timeout"
        product_image_obj.processed = True
        product_image_obj.save()
        return {'success': False, 'reason': 'Timeout'}

    except requests.exceptions.RequestException as e:
        product_image_obj.status = ProductImage.ImageStatus.FAILED
        product_image_obj.error_message = f"Request Exception: {str(e)[:100]}"
        product_image_obj.processed = True
        product_image_obj.save()
        return {'success': False, 'reason': str(e)}

    except Exception as e:
        product_image_obj.status = ProductImage.ImageStatus.FAILED
        product_image_obj.error_message = f"Corrupted Image: {str(e)[:100]}"
        product_image_obj.processed = True
        product_image_obj.save()
        return {'success': False, 'reason': 'Corrupted Image'}
