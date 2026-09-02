from django.contrib import admin
from taxonomy.models import TaxonomyCategory, TaxonomyAttribute

@admin.register(TaxonomyCategory)
class TaxonomyCategoryAdmin(admin.ModelAdmin):
    list_display = ('shopify_id', 'name', 'full_path', 'level', 'parent')
    search_fields = ('name', 'full_path', 'shopify_id')
    list_filter = ('level',)

@admin.register(TaxonomyAttribute)
class TaxonomyAttributeAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'gid', 'value_type')
    search_fields = ('name', 'gid')
