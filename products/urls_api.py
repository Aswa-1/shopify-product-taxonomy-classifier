from django.urls import path, include
from rest_framework.routers import DefaultRouter
from products.views_api import ProductViewSet, ImportViewSet, JobViewSet, TaxonomyViewSet

router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product')
router.register(r'import', ImportViewSet, basename='import')
router.register(r'jobs', JobViewSet, basename='job')
router.register(r'taxonomy', TaxonomyViewSet, basename='taxonomy')

urlpatterns = [
    path('', include(router.urls)),
]
