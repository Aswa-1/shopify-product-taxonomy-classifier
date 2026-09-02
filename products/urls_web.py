from django.urls import path
from products import views_web

urlpatterns = [
    path('', views_web.dashboard_view, name='dashboard'),
    path('products/', views_web.products_list_view, name='products_list'),
    path('products/<int:pk>/', views_web.product_detail_view, name='product_detail'),
    path('review/', views_web.review_queue_view, name='review_queue'),
    path('import/', views_web.import_upload_view, name='import_upload'),
]
