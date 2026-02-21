import requests
from typing import Dict, List
import time
import math


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the straight-line distance between two coordinates (in km)
    using the Haversine formula.
    """
    R = 6371  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return round(2 * R * math.asin(math.sqrt(a)), 1)


def geocode_location(location: str) -> Dict:
    """
    Geocode a location string to coordinates using Nominatim (OpenStreetMap)

    Args:
        location: Location string (address, city, etc.)

    Returns:
        dict: Location data with coordinates
    """
    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            'q': location,
            'format': 'json',
            'limit': 1,
            'addressdetails': 1
        }
        headers = {'User-Agent': 'EmergencyCallAssistant/1.0'}

        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data:
            result = data[0]
            return {
                'lat': float(result['lat']),
                'lon': float(result['lon']),
                'display_name': result['display_name'],
                'found': True
            }
        return {'found': False, 'error': 'Location not found'}

    except Exception as e:
        print(f"Geocoding error: {str(e)}")
        return {'found': False, 'error': str(e)}


def find_nearby_emergency_services(lat: float, lon: float, radius: int = 5000) -> List[Dict]:
    """
    Find the 5 nearest real emergency help centres (hospitals, clinics,
    police stations, fire stations) sorted by distance.

    Args:
        lat: Latitude of the incident
        lon: Longitude of the incident
        radius: Search radius in metres (default 5 km)

    Returns:
        list: Up to 5 nearby services with distance_km field
    """
    overpass_urls = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
    ]

    # Include clinics alongside the original amenity types
    query = f"""
    [out:json][timeout:20];
    (
      node["amenity"="hospital"](around:{radius},{lat},{lon});
      node["amenity"="clinic"](around:{radius},{lat},{lon});
      node["amenity"="doctors"](around:{radius},{lat},{lon});
      node["amenity"="police"](around:{radius},{lat},{lon});
      node["amenity"="fire_station"](around:{radius},{lat},{lon});
      way["amenity"="hospital"](around:{radius},{lat},{lon});
      way["amenity"="clinic"](around:{radius},{lat},{lon});
    );
    out center body;
    """

    # Human-readable label for each amenity type
    TYPE_LABEL = {
        'hospital':     'Hospital',
        'clinic':       'Clinic',
        'doctors':      'Clinic',
        'police':       'Police Station',
        'fire_station': 'Fire Station',
    }

    for overpass_url in overpass_urls:
        try:
            print(f"Trying Overpass API: {overpass_url}")
            response = requests.post(
                overpass_url,
                data={'data': query},
                timeout=25,
                headers={'User-Agent': 'EmergencyCallAssistant/1.0'}
            )
            response.raise_for_status()
            data = response.json()

            services = []
            for element in data.get('elements', []):
                tags = element.get('tags', {})
                name = tags.get('name', '').strip()
                if not name:          # skip unnamed features
                    continue

                amenity = tags.get('amenity', 'unknown')

                # Resolve coordinates for nodes and ways
                if element['type'] == 'node':
                    s_lat, s_lon = element['lat'], element['lon']
                elif element['type'] == 'way' and 'center' in element:
                    s_lat, s_lon = element['center']['lat'], element['center']['lon']
                else:
                    continue

                dist_km = haversine_distance(lat, lon, s_lat, s_lon)

                services.append({
                    'type':        amenity,
                    'type_label':  TYPE_LABEL.get(amenity, amenity.replace('_', ' ').title()),
                    'name':        name,
                    'lat':         s_lat,
                    'lon':         s_lon,
                    'distance_km': dist_km
                })

            # Sort by real-world distance and keep closest 5
            services.sort(key=lambda x: x['distance_km'])
            top5 = services[:5]

            print(f"Found {len(services)} services, returning top 5 by distance")
            return top5

        except requests.exceptions.Timeout:
            print(f"Timeout with {overpass_url}, trying next...")
            time.sleep(1)
            continue
        except Exception as e:
            print(f"Error with {overpass_url}: {str(e)}")
            continue

    print("All Overpass API servers failed or timed out")
    return []


def get_location_data(location: str) -> Dict:
    """
    Get complete location data including coordinates and 5 nearest help centres.

    Args:
        location: Location string

    Returns:
        dict: Complete location data
    """
    geocode_result = geocode_location(location)

    if not geocode_result.get('found'):
        return geocode_result

    lat = geocode_result['lat']
    lon = geocode_result['lon']

    services = find_nearby_emergency_services(lat, lon)

    return {
        'found': True,
        'location': {
            'lat': lat,
            'lon': lon,
            'display_name': geocode_result['display_name']
        },
        'emergency_services': services
    }