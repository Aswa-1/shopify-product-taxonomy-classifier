from django.db import models

class TaxonomyCategory(models.Model):
    shopify_id = models.CharField(max_length=100, unique=True, db_index=True)
    gid = models.CharField(max_length=200, blank=True, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    full_path = models.TextField(db_index=True)
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='children',
        db_index=True
    )
    level = models.IntegerField(default=1, db_index=True)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name_plural = 'Taxonomy Categories'
        ordering = ['full_path']
        indexes = [
            models.Index(fields=['shopify_id']),
            models.Index(fields=['parent']),
            models.Index(fields=['name']),
            models.Index(fields=['level']),
        ]

    def __str__(self):
        return self.full_path


class TaxonomyAttribute(models.Model):
    category = models.ForeignKey(
        TaxonomyCategory,
        on_delete=models.CASCADE,
        related_name='attributes',
        null=True,
        blank=True
    )
    gid = models.CharField(max_length=200, blank=True, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    value_type = models.CharField(max_length=100, default='string', blank=True)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['name']),
        ]

    def __str__(self):
        return f"{self.name} ({self.category.name if self.category else 'Global'})"


class TaxonomyAttributeValue(models.Model):
    attribute = models.ForeignKey(
        TaxonomyAttribute,
        on_delete=models.CASCADE,
        related_name='values',
        db_index=True
    )
    gid = models.CharField(max_length=200, db_index=True)
    value = models.CharField(max_length=500, db_index=True)
    normalized_value = models.CharField(max_length=500, db_index=True)

    class Meta:
        ordering = ['value']
        constraints = [
            models.UniqueConstraint(fields=['attribute', 'gid'], name='unique_taxonomy_attribute_value_gid'),
            models.UniqueConstraint(fields=['attribute', 'normalized_value'], name='unique_taxonomy_attribute_value_normalized'),
        ]
        indexes = [
            models.Index(fields=['attribute', 'normalized_value']),
            models.Index(fields=['gid']),
        ]

    def __str__(self):
        return f"{self.attribute.name}: {self.value}"
