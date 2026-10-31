"use client";

import {
  APIProvider,
  AdvancedMarker,
  AdvancedMarkerAnchorPoint,
  ColorScheme,
  InfoWindow,
  Map,
  Polyline,
  useAdvancedMarkerRef,
  useMap,
} from "@vis.gl/react-google-maps";
import { useEffect, useMemo, useRef, useState } from "react";

import type { LatLngLiteral } from "@/lib/polyline";
import { chargerKey, haversineKm, type TripState } from "@/lib/trip-state";
import type { ChargeStopResult, Place, UserLocation } from "@/lib/types";

import ChargerMarker, { AVAILABILITY_STYLES } from "./ChargerMarker";
import type { MapsConfigState } from "./EvCopilotApp";
import { MapIcon, SpinnerIcon, StarIcon } from "./Icons";

interface MapPanelProps {
  configState: MapsConfigState;
  trip: TripState;
  userLocation: UserLocation | null;
  selectedChargerId: string | null;
  onSelectCharger: (chargerId: string | null) => void;
  dark: boolean;
}

const WORLD_CENTER: LatLngLiteral = { lat: 20, lng: 0 };
const FIT_PADDING = { top: 56, right: 56, bottom: 56, left: 56 };
/** A charger within this distance of a planned stop is drawn highlighted. */
const STOP_MATCH_KM = 0.3;

const toLiteral = (p: { latitude: number; longitude: number }): LatLngLiteral => ({ lat: p.latitude, lng: p.longitude });

export default function MapPanel({ configState, trip, userLocation, selectedChargerId, onSelectCharger, dark }: MapPanelProps) {
  if (configState.status === "loading") {
    return (
      <div className="relative flex min-h-[280px] flex-1 items-center justify-center bg-surface-3 text-ink-3">
        <SpinnerIcon size={20} />
      </div>
    );
  }

  const { mapsApiKey, mapId } = configState.config;
  if (!mapsApiKey) return <MapPlaceholder trip={trip} />;

  return (
    <div className="relative min-h-[280px] flex-1 bg-surface-3">
      <APIProvider apiKey={mapsApiKey}>
        <Map
          key={dark ? "dark" : "light"}
          mapId={mapId}
          defaultCenter={userLocation ? toLiteral(userLocation) : WORLD_CENTER}
          defaultZoom={userLocation ? 11 : 2}
          gestureHandling="greedy"
          colorScheme={dark ? ColorScheme.DARK : ColorScheme.LIGHT}
          mapTypeControl={false}
          streetViewControl={false}
          fullscreenControl={false}
          clickableIcons={false}
          className="absolute inset-0"
        >
          <TripLayers trip={trip} userLocation={userLocation} selectedChargerId={selectedChargerId} onSelectCharger={onSelectCharger} />
        </Map>
      </APIProvider>
      <MapLegend hasStops={(trip.plan?.stops.length ?? 0) > 0} hasPlaces={trip.places.length > 0} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Layers
// ---------------------------------------------------------------------------

function TripLayers({
  trip,
  userLocation,
  selectedChargerId,
  onSelectCharger,
}: Omit<MapPanelProps, "configState" | "dark">) {
  const stops = useMemo(() => trip.plan?.stops ?? [], [trip.plan]);
  const stopPoints = useMemo(() => stops.map((s) => toLiteral(s.location)), [stops]);

  return (
    <>
      {trip.route && trip.route.path.length > 1 && (
        <>
          <Polyline path={trip.route.path} strokeColor="#ffffff" strokeOpacity={0.9} strokeWeight={8} zIndex={1} />
          <Polyline path={trip.route.path} strokeColor="#059669" strokeOpacity={1} strokeWeight={5} zIndex={2} />
        </>
      )}

      {userLocation && <UserMarker position={toLiteral(userLocation)} />}

      {trip.route?.origin && <EndpointMarker position={trip.route.origin} label="A" title="Start" />}
      {trip.route?.destination && <EndpointMarker position={trip.route.destination} label="B" title="Destination" />}

      {trip.places.map((place) => (
        <PlaceMarker key={place.place_id || `${place.name}-${place.location.latitude}-${place.location.longitude}`} place={place} />
      ))}

      {trip.chargers.map((charger) => (
        <ChargerMarker
          key={chargerKey(charger)}
          charger={charger}
          selected={chargerKey(charger) === selectedChargerId}
          highlighted={stopPoints.some((p) => haversineKm(p, toLiteral(charger.location)) <= STOP_MATCH_KM)}
          onSelect={onSelectCharger}
        />
      ))}

      {stops.map((stop, i) => (
        <StopMarker key={`${stop.index}-${i}`} stop={stop} number={i + 1} />
      ))}

      <FitBounds trip={trip} userLocation={userLocation} selectedChargerId={selectedChargerId} />
    </>
  );
}

function UserMarker({ position }: { position: LatLngLiteral }) {
  return (
    <AdvancedMarker position={position} anchorPoint={AdvancedMarkerAnchorPoint.CENTER} zIndex={5} title="Your location">
      <span className="relative flex h-4 w-4">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-sky-400 opacity-60" />
        <span className="relative inline-flex h-4 w-4 rounded-full border-2 border-white bg-sky-500 shadow" />
      </span>
    </AdvancedMarker>
  );
}

function EndpointMarker({ position, label, title }: { position: LatLngLiteral; label: string; title: string }) {
  return (
    <AdvancedMarker position={position} anchorPoint={AdvancedMarkerAnchorPoint.BOTTOM} zIndex={50} title={title}>
      <div className="flex flex-col items-center">
        <span className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-white bg-slate-900 text-xs font-bold text-white shadow-md">
          {label}
        </span>
        <span className="-mt-0.5 h-2 w-0.5 bg-slate-900" />
      </div>
    </AdvancedMarker>
  );
}

function StopMarker({ stop, number }: { stop: ChargeStopResult; number: number }) {
  const [markerRef, marker] = useAdvancedMarkerRef();
  const [open, setOpen] = useState(false);
  return (
    <>
      <AdvancedMarker
        ref={markerRef}
        position={toLiteral(stop.location)}
        anchorPoint={AdvancedMarkerAnchorPoint.BOTTOM}
        zIndex={900}
        title={`Stop ${number}: ${stop.name}`}
        onClick={() => setOpen((v) => !v)}
      >
        <div className="flex flex-col items-center">
          <span className="flex h-8 w-8 items-center justify-center rounded-full border-[2.5px] border-white bg-emerald-600 text-sm font-bold text-white shadow-lg ring-2 ring-emerald-700/40">
            {number}
          </span>
          <span className="-mt-0.5 h-2.5 w-0.5 bg-emerald-700" />
        </div>
      </AdvancedMarker>
      {open && marker && (
        <InfoWindow anchor={marker} onCloseClick={() => setOpen(false)} maxWidth={260}>
          <div className="w-[230px] p-3 font-sans text-slate-800">
            <div className="text-[11px] font-semibold tracking-wide text-emerald-700 uppercase">Charging stop {number}</div>
            <div className="mt-0.5 pr-6 text-sm font-semibold text-slate-900">{stop.name || "Charging stop"}</div>
            <div className="mt-1.5 text-xs text-slate-600">
              Arrive {Math.round(stop.arrival_soc_percent)}% → leave {Math.round(stop.departure_soc_percent)}%
            </div>
            <div className="text-xs text-slate-600">
              {Math.round(stop.charge_min)} min at {Math.round(stop.charger_power_kw)} kW · +{stop.energy_added_kwh.toFixed(1)} kWh
            </div>
          </div>
        </InfoWindow>
      )}
    </>
  );
}

function PlaceMarker({ place }: { place: Place }) {
  const [markerRef, marker] = useAdvancedMarkerRef();
  const [open, setOpen] = useState(false);
  if (place.location.latitude === null || place.location.longitude === null) return null;
  return (
    <>
      <AdvancedMarker
        ref={markerRef}
        position={{ lat: place.location.latitude, lng: place.location.longitude }}
        anchorPoint={AdvancedMarkerAnchorPoint.CENTER}
        zIndex={10}
        title={place.name}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="block h-3.5 w-3.5 rounded-full border-2 border-white bg-indigo-500 shadow" />
      </AdvancedMarker>
      {open && marker && (
        <InfoWindow anchor={marker} onCloseClick={() => setOpen(false)} maxWidth={260}>
          <div className="w-[230px] p-3 font-sans text-slate-800">
            <div className="pr-6 text-sm font-semibold text-slate-900">{place.name}</div>
            {place.address && <div className="mt-0.5 text-xs text-slate-500">{place.address}</div>}
            {typeof place.rating === "number" && (
              <div className="mt-1 flex items-center gap-0.5 text-xs text-slate-600">
                <StarIcon size={12} className="text-amber-500" />
                {place.rating.toFixed(1)}
                {typeof place.review_count === "number" && <span className="text-slate-400"> ({place.review_count})</span>}
              </div>
            )}
            {place.summary && <div className="mt-1 text-xs text-slate-600">{place.summary}</div>}
          </div>
        </InfoWindow>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Camera
// ---------------------------------------------------------------------------

function FitBounds({ trip, userLocation, selectedChargerId }: Pick<MapPanelProps, "trip" | "userLocation" | "selectedChargerId">) {
  const map = useMap();
  const centeredOnUser = useRef(false);

  // Re-fit whenever new route/charger data arrives.
  useEffect(() => {
    if (!map || trip.fitVersion === 0) return;
    const points: LatLngLiteral[] = [];
    if (trip.route && trip.route.path.length > 0) {
      points.push(...trip.route.path);
      trip.plan?.stops.forEach((s) => points.push(toLiteral(s.location)));
    } else {
      trip.chargers.forEach((c) => points.push(toLiteral(c.location)));
      if (userLocation) points.push(toLiteral(userLocation));
    }
    if (points.length === 0) return;
    if (points.length === 1) {
      map.panTo(points[0]);
      map.setZoom(13);
      return;
    }
    const bounds = new google.maps.LatLngBounds();
    points.forEach((p) => bounds.extend(p));
    map.fitBounds(bounds, FIT_PADDING);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fit only when fitVersion changes
  }, [map, trip.fitVersion]);

  // Before any trip data: centre on the user once their location is known.
  useEffect(() => {
    if (!map || !userLocation || trip.fitVersion > 0 || centeredOnUser.current) return;
    centeredOnUser.current = true;
    map.panTo(toLiteral(userLocation));
    map.setZoom(11);
  }, [map, userLocation, trip.fitVersion]);

  // Pan to a charger picked from the trip panel list.
  useEffect(() => {
    if (!map || !selectedChargerId) return;
    const charger = trip.chargers.find((c) => chargerKey(c) === selectedChargerId);
    if (charger) map.panTo(toLiteral(charger.location));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- pan only on selection change
  }, [map, selectedChargerId]);

  return null;
}

// ---------------------------------------------------------------------------
// Chrome
// ---------------------------------------------------------------------------

function MapLegend({ hasStops, hasPlaces }: { hasStops: boolean; hasPlaces: boolean }) {
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 flex flex-wrap gap-x-3 gap-y-1 rounded-lg border border-black/5 bg-white/90 px-2.5 py-1.5 text-[11px] text-slate-700 shadow-sm backdrop-blur">
      {Object.entries(AVAILABILITY_STYLES).map(([level, { color, label }]) => (
        <span key={level} className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full border border-white" style={{ background: color }} />
          {label}
        </span>
      ))}
      {hasStops && (
        <span className="flex items-center gap-1.5">
          <span className="flex h-3.5 w-3.5 items-center justify-center rounded-full bg-emerald-600 text-[8px] font-bold text-white">1</span>
          Planned stop
        </span>
      )}
      {hasPlaces && (
        <span className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-indigo-500" />
          Place
        </span>
      )}
    </div>
  );
}

/** Shown when GOOGLE_MAPS_BROWSER_API_KEY is not configured: the trip panel still works. */
function MapPlaceholder({ trip }: { trip: TripState }) {
  return (
    <div
      className="relative flex min-h-[220px] flex-1 items-center justify-center overflow-hidden bg-surface-3 p-6"
      style={{
        backgroundImage:
          "linear-gradient(var(--border) 1px, transparent 1px), linear-gradient(90deg, var(--border) 1px, transparent 1px)",
        backgroundSize: "32px 32px",
      }}
    >
      <div className="max-w-sm rounded-2xl border border-line bg-surface/95 p-5 text-center shadow-sm">
        <span className="mx-auto flex h-10 w-10 items-center justify-center rounded-xl bg-accent-soft text-accent-ink">
          <MapIcon size={20} />
        </span>
        <div className="mt-3 text-sm font-semibold text-ink">Map not configured</div>
        <p className="mt-1 text-xs leading-relaxed text-ink-3">
          Set <code className="rounded bg-surface-3 px-1 font-mono">GOOGLE_MAPS_BROWSER_API_KEY</code> to see your route,
          chargers and stops on a live map. Trip details below still update as you chat.
        </p>
        {(trip.route || trip.chargers.length > 0) && (
          <p className="mt-3 text-xs font-medium text-ink-2">
            {trip.route ? "Route ready" : ""}
            {trip.route && trip.chargers.length > 0 ? " · " : ""}
            {trip.chargers.length > 0 ? `${trip.chargers.length} charger${trip.chargers.length === 1 ? "" : "s"} found` : ""}
          </p>
        )}
      </div>
    </div>
  );
}
