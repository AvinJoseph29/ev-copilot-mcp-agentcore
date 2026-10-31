/**
 * Google encoded polyline decoder (precision 5).
 * Algorithm: https://developers.google.com/maps/documentation/utilities/polylinealgorithm
 */

export interface LatLngLiteral {
  lat: number;
  lng: number;
}

export function decodePolyline(encoded: string, precision = 5): LatLngLiteral[] {
  const points: LatLngLiteral[] = [];
  if (!encoded) return points;

  const factor = 10 ** precision;
  let index = 0;
  let lat = 0;
  let lng = 0;

  while (index < encoded.length) {
    let result = 0;
    let shift = 0;
    let byte: number;
    do {
      byte = encoded.charCodeAt(index++) - 63;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20 && index < encoded.length);
    lat += result & 1 ? ~(result >> 1) : result >> 1;

    result = 0;
    shift = 0;
    do {
      byte = encoded.charCodeAt(index++) - 63;
      result |= (byte & 0x1f) << shift;
      shift += 5;
    } while (byte >= 0x20 && index < encoded.length);
    lng += result & 1 ? ~(result >> 1) : result >> 1;

    points.push({ lat: lat / factor, lng: lng / factor });
  }

  return points;
}
