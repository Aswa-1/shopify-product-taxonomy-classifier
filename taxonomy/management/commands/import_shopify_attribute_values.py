from django.core.management.base import BaseCommand

from taxonomy.importer import import_shopify_attribute_values


class Command(BaseCommand):
    help = 'Imports Shopify taxonomy attribute values from the project attribute_values.txt file.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE('Starting Shopify taxonomy attribute value import...'))
        try:
            result = import_shopify_attribute_values()
            self.stdout.write(
                self.style.SUCCESS(
                    'Attribute value import summary: '
                    f'total_lines={result["total_lines"]}, '
                    f'successfully_imported={result["successfully_imported"]}, '
                    f'skipped={result["skipped"]}, '
                    f'unmatched_attributes={result["unmatched_attributes"]}, '
                    f'invalid_lines={result["invalid_lines"]}'
                )
            )
        except Exception as exc:  # pragma: no cover
            self.stdout.write(self.style.ERROR(f'Import failed: {exc}'))
