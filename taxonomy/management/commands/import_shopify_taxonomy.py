from django.core.management.base import BaseCommand
from taxonomy.importer import import_shopify_taxonomy

class Command(BaseCommand):
    help = 'Imports the official English Shopify Product Taxonomy from GitHub'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Starting Shopify Taxonomy import...'))
        try:
            result = import_shopify_taxonomy()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully imported {result['total_categories']} categories "
                    f"and {result['total_attributes']} attributes!"
                )
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Import failed: {e}"))
