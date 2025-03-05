# game/management/commands/import_countries.py
import requests
from django.core.management.base import BaseCommand
from game.models import Country

class Command(BaseCommand):
    help = "Import country data from the REST Countries API and populate the Country table."

    def handle(self, *args, **options):
        url = "https://restcountries.com/v3.1/all"
        response = requests.get(url)
        if response.status_code != 200:
            self.stderr.write("Failed to fetch country data. Please try again later.")
            return
        
        data = response.json()
        self.stdout.write("Fetched country data successfully.")
        
        # Use a dictionary to store created Country objects keyed by their CCA3 code.
        country_map = {}
        
        # First pass: Create Country objects without neighbor relations.
        for entry in data:
            try:
                name = entry["name"]["common"]
                population = entry.get("population", 0)
                # Compute "strength" as at least 1 word, or more based on population.
                strength = max(1, int(population / 100000000))
                # Create or update the Country record.
                country_obj, created = Country.objects.get_or_create(
                    name=name,
                    defaults={
                        "population": population,
                        "strength": strength,
                    }
                )
                # Use the CCA3 code as key (e.g., "USA", "FRA").
                cca3 = entry.get("cca3")
                if cca3:
                    country_map[cca3] = country_obj
            except Exception as e:
                self.stderr.write(f"Error processing country {entry.get('name', {}).get('common', 'Unknown')}: {e}")

        self.stdout.write(f"Created {len(country_map)} country records.")
        
        # Second pass: Set neighbor relationships.
        for entry in data:
            cca3 = entry.get("cca3")
            if not cca3 or cca3 not in country_map:
                continue
            country_obj = country_map[cca3]
            borders = entry.get("borders", [])
            for border_code in borders:
                neighbor = country_map.get(border_code)
                if neighbor:
                    country_obj.neighbors.add(neighbor)
            country_obj.save()
        
        self.stdout.write(self.style.SUCCESS("Successfully imported country data and updated neighbor relationships."))
