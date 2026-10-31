"""
Google encoded-polyline helpers and geodesic utilities.

Pure functions (no I/O):
- decode / encode the Google Encoded Polyline Algorithm Format
- haversine great-circle distance
- cumulative distances along a path
- even down-sampling of long paths (keeps Elevation API URLs short)

All coordinates are (latitude, longitude) tuples.
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088

LatLngTuple = tuple[float, float]


# ---------------------------------------------------------------------------
# Encoded polyline (precision 5)
# ---------------------------------------------------------------------------


def decode_polyline(encoded: str, precision: int = 5) -> list[LatLngTuple]:
    """Decode a Google encoded polyline into a list of (lat, lng) tuples."""
    if not encoded:
        return []

    factor = 10**precision
    coordinates: list[LatLngTuple] = []
    index = lat = lng = 0
    length = len(encoded)

    while index < length:
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lng += deltas[1]
        coordinates.append((lat / factor, lng / factor))

    return coordinates


def _encode_value(value: int) -> str:
    value = ~(value << 1) if value < 0 else value << 1
    chunks = []
    while value >= 0x20:
        chunks.append(chr((0x20 | (value & 0x1F)) + 63))
        value >>= 5
    chunks.append(chr(value + 63))
    return "".join(chunks)


def encode_polyline(coordinates: list[LatLngTuple], precision: int = 5) -> str:
    """Encode a list of (lat, lng) tuples as a Google encoded polyline."""
    factor = 10**precision
    output = []
    prev_lat = prev_lng = 0
    for lat, lng in coordinates:
        lat_i = round(lat * factor)
        lng_i = round(lng * factor)
        output.append(_encode_value(lat_i - prev_lat))
        output.append(_encode_value(lng_i - prev_lng))
        prev_lat, prev_lng = lat_i, lng_i
    return "".join(output)


# ---------------------------------------------------------------------------
# Distances
# ---------------------------------------------------------------------------


def haversine_km(a: LatLngTuple, b: LatLngTuple) -> float:
    """Great-circle distance between two (lat, lng) points in kilometres."""
    lat1, lng1 = map(math.radians, a)
    lat2, lng2 = map(math.radians, b)
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def cumulative_distances_km(points: list[LatLngTuple]) -> list[float]:
    """Cumulative distance (km) from the first point for every point in the path."""
    distances = [0.0] * len(points)
    for i in range(1, len(points)):
        distances[i] = distances[i - 1] + haversine_km(points[i - 1], points[i])
    return distances


def downsample(points: list[LatLngTuple], max_points: int) -> list[LatLngTuple]:
    """Evenly down-sample a path to at most ``max_points`` (keeps both endpoints)."""
    if max_points < 2 or len(points) <= max_points:
        return list(points)
    step = (len(points) - 1) / (max_points - 1)
    return [points[round(i * step)] for i in range(max_points)]


def shorten_polyline(encoded: str, max_points: int = 150) -> str:
    """Re-encode a polyline with at most ``max_points`` vertices.

    Keeps GET request URLs (e.g. Elevation API ``path=enc:...``) well under
    the 16 384-character limit for long routes.
    """
    points = decode_polyline(encoded)
    if len(points) <= max_points:
        return encoded
    return encode_polyline(downsample(points, max_points))
