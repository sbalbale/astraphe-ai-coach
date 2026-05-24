<script lang="ts">
  import { browser } from '$app/environment';
  import * as d3 from 'd3';
  import type { ZoneDef } from '$lib/services/activityService';
  import {
    HR_ZONE_COLOR_BY_INDEX,
    bpmToHrZone,
    formatHrZoneTitle,
  } from '$lib/hrZoneDisplay';
  import { decodePolyline } from '$lib/utils/polyline';
  import 'maplibre-gl/dist/maplibre-gl.css';
  import { onMount, tick } from 'svelte';
  import type { Map as MapLibreMap } from 'maplibre-gl';

  const STYLE = {
    version: 8 as const,
    sources: {
      'carto-dark': {
        type: 'raster' as const,
        tiles: [
          'https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png',
          'https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png',
          'https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png',
        ],
        tileSize: 256,
        minzoom: 0,
        maxzoom: 22,
        attribution:
          '© <a href="https://carto.com/">CARTO</a> © <a href="https://www.openstreetmap.org/">OSM</a>',
      },
    },
    layers: [{ id: 'carto-dark-layer', type: 'raster' as const, source: 'carto-dark' }],
  };

  const ZONE_COLORS = HR_ZONE_COLOR_BY_INDEX;

  const HR_LEGEND_ZONES = [1, 2, 3, 4, 5] as const;

  const PREVIEW_HEIGHT =
    'h-[240px] md:h-[min(28rem,52vh)] md:min-h-[22rem]';

  let {
    latlng = [],
    polyline = null,
    heartrate = undefined,
    time = undefined,
    zones = undefined,
  }: {
    latlng?: [number, number][];
    polyline?: string | null;
    heartrate?: number[];
    /** Stream time in seconds; required when route point count ≠ heartrate length. */
    time?: number[];
    zones?: ZoneDef[];
  } = $props();

  const routeLatLng = $derived<[number, number][]>(
    latlng.length >= 2 ? latlng : polyline ? decodePolyline(polyline) : []
  );

  const hrMode = $derived(Boolean(heartrate?.length && zones?.length && routeLatLng.length >= 2));

  let mapContainer = $state<HTMLDivElement | null>(null);
  let mapInstance = $state<MapLibreMap | null>(null);
  let clientReady = $state(false);
  let mapExpanded = $state(false);

  let workerUrlSet = false;

  function openMap() {
    mapExpanded = true;
  }

  function closeMap() {
    mapExpanded = false;
  }

  function onWindowKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape' && mapExpanded) closeMap();
  }

  function bumpMapResize() {
    if (!mapInstance) return;
    requestAnimationFrame(() => {
      mapInstance?.resize();
      requestAnimationFrame(() => mapInstance?.resize());
    });
  }

  function fitMapToRoute(
    map: MapLibreMap,
    coords: [number, number][],
    LngLatBounds: typeof import('maplibre-gl').LngLatBounds
  ) {
    if (coords.length < 2) return;
    const bounds = coords.reduce(
      (b, c) => b.extend(c),
      new LngLatBounds(coords[0], coords[0])
    );
    map.fitBounds(bounds, { padding: 48, animate: false });
  }

  function setMapInteractive(map: MapLibreMap, enabled: boolean) {
    const toggle = enabled ? 'enable' : 'disable';
    map.dragPan[toggle]();
    map.dragRotate[toggle]();
    map.scrollZoom[toggle]();
    map.boxZoom[toggle]();
    map.doubleClickZoom[toggle]();
    map.touchZoomRotate[toggle]();
    map.touchPitch[toggle]();
    map.keyboard[toggle]();
  }

  function routeCoordsLngLat(): [number, number][] {
    return routeLatLng.map(([lat, lng]) => [lng, lat] as [number, number]);
  }

  async function syncMapExpandedState(expanded: boolean) {
    const map = mapInstance;
    if (!map || routeLatLng.length < 2) return;

    setMapInteractive(map, expanded);
    bumpMapResize();

    const ml = await import('maplibre-gl');
    if (!mapInstance) return;

    // On open: start fitted to the route. On close: undo pan/zoom from the session.
    fitMapToRoute(mapInstance, routeCoordsLngLat(), ml.LngLatBounds);
  }

  async function ensureWorker(ml: typeof import('maplibre-gl')) {
    if (workerUrlSet || !browser) return;
    const workerMod = await import('maplibre-gl/dist/maplibre-gl-csp-worker.js?url');
    const url = workerMod.default as string;
    ml.setWorkerUrl(url);
    workerUrlSet = true;
  }

  onMount(() => {
    clientReady = true;
    return () => {
      mapInstance?.remove();
      mapInstance = null;
    };
  });

  $effect(() => {
    if (!browser) return;
    document.body.style.overflow = mapExpanded ? 'hidden' : '';
    return () => {
      document.body.style.overflow = '';
    };
  });

  $effect(() => {
    const expanded = mapExpanded;
    mapInstance;
    void tick().then(() => syncMapExpandedState(expanded));
  });

  $effect(() => {
    routeLatLng;
    closeMap();
  });

  function getZone(bpm: number, zoneList: ZoneDef[]): number {
    if (!Number.isFinite(bpm) || bpm <= 0) return 0;
    return bpmToHrZone(zoneList, bpm);
  }

  function resampleHrToRoute(
    numCoords: number,
    hr: number[],
    timeSec: number[] | undefined
  ): number[] {
    if (numCoords < 1 || !hr.length) return [];
    if (numCoords === hr.length) return hr;

    const tArr =
      timeSec?.length === hr.length ? timeSec : hr.map((_, i) => i);
    const tMin = tArr[0] ?? 0;
    const tMax = tArr[tArr.length - 1] ?? hr.length - 1;
    const span = tMax - tMin;

    const out: number[] = new Array(numCoords);
    for (let i = 0; i < numCoords; i++) {
      const frac = numCoords <= 1 ? 0 : i / (numCoords - 1);
      const targetT = span > 0 ? tMin + frac * span : tMin;
      const idx = Math.min(d3.bisectLeft(tArr, targetT), hr.length - 1);
      out[i] = hr[idx];
    }
    return out;
  }

  function buildHrMergedLineFeatures(
    coords: [number, number][],
    hr: number[],
    zoneList: ZoneDef[]
  ): GeoJSON.Feature[] {
    const n = coords.length;
    if (n < 2) return [];

    const features: GeoJSON.Feature[] = [];
    let runCoords: [number, number][] | null = null;
    let runColor: string | null = null;

    const flushRun = (): void => {
      if (!runCoords || runCoords.length < 2 || runColor == null) {
        runCoords = null;
        runColor = null;
        return;
      }
      features.push({
        type: 'Feature',
        properties: { color: runColor },
        geometry: {
          type: 'LineString',
          coordinates: [...runCoords],
        },
      });
      runCoords = null;
      runColor = null;
    };

    for (let i = 0; i < n - 1; i++) {
      const bpm = hr[i];
      const z = bpm == null || !Number.isFinite(bpm) ? 0 : getZone(bpm, zoneList);
      const color = ZONE_COLORS[z] ?? ZONE_COLORS[0];

      if (runColor !== color) {
        flushRun();
        runColor = color;
        runCoords = [coords[i], coords[i + 1]];
      } else {
        runCoords!.push(coords[i + 1]);
      }
    }
    flushRun();
    return features;
  }

  function buildRouteCasingGeoJson(coords: [number, number][]): GeoJSON.FeatureCollection {
    return {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: {},
          geometry: { type: 'LineString', coordinates: coords },
        },
      ],
    };
  }

  function buildRouteGeoJson(
    coords: [number, number][],
    hr: number[] | undefined,
    zoneList: ZoneDef[] | undefined,
    timeSec: number[] | undefined
  ): GeoJSON.FeatureCollection {
    const useHr = Boolean(hr?.length && zoneList?.length);

    if (useHr && hr && zoneList) {
      const hrAligned = resampleHrToRoute(coords.length, hr, timeSec);
      const features = buildHrMergedLineFeatures(coords, hrAligned, zoneList);
      return { type: 'FeatureCollection', features };
    }

    return {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: {},
          geometry: {
            type: 'LineString',
            coordinates: coords,
          },
        },
      ],
    };
  }

  function buildEndpointsGeoJson(coords: [number, number][]): GeoJSON.FeatureCollection {
    return {
      type: 'FeatureCollection',
      features: [
        {
          type: 'Feature',
          properties: { color: '#00C8A8' },
          geometry: { type: 'Point', coordinates: coords[0] },
        },
        {
          type: 'Feature',
          properties: { color: '#F07178' },
          geometry: { type: 'Point', coordinates: coords[coords.length - 1] },
        },
      ],
    };
  }

  $effect(() => {
    if (!browser || !clientReady || routeLatLng.length < 2 || !mapContainer) return;

    let cancelled = false;
    let ro: ResizeObserver | null = null;

    void (async () => {
      await tick();
      const ml = await import('maplibre-gl');
      await ensureWorker(ml);

      if (cancelled || !mapContainer) return;

      mapInstance?.remove();
      mapInstance = null;

      const { Map, LngLatBounds } = ml;

      const coords = routeLatLng.map(([lat, lng]) => [lng, lat] as [number, number]);
      const routeData = buildRouteGeoJson(coords, heartrate, zones, time);
      const hr = Boolean(heartrate?.length && zones?.length);
      const endpointData = buildEndpointsGeoJson(coords);

      const map = new Map({
        container: mapContainer,
        style: STYLE as import('maplibre-gl').StyleSpecification,
        attributionControl: false,
      });

      if (cancelled) {
        map.remove();
        return;
      }
      mapInstance = map;

      map.on('error', (e) => {
        console.warn('[GpsTrace] MapLibre error', e.error);
      });

      map.on('load', () => {
        if (cancelled) return;
        try {
          if (hr) {
            map.addSource('route-casing', {
              type: 'geojson',
              data: buildRouteCasingGeoJson(coords),
            });
            map.addLayer({
              id: 'route-line-casing',
              type: 'line',
              source: 'route-casing',
              layout: {
                'line-cap': 'round',
                'line-join': 'round',
              },
              paint: {
                'line-color': '#0F0F1A',
                'line-opacity': 0.92,
                'line-width': 9,
              },
            });
          }

          map.addSource('route', { type: 'geojson', data: routeData });
          map.addLayer({
            id: 'route-line',
            type: 'line',
            source: 'route',
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: {
              'line-color': hr ? ['get', 'color'] : '#4621FF',
              'line-width': 4,
              'line-opacity': 1,
            },
          });

          map.addSource('endpoints', { type: 'geojson', data: endpointData });
          map.addLayer({
            id: 'endpoints-layer',
            type: 'circle',
            source: 'endpoints',
            paint: {
              'circle-radius': 6,
              'circle-color': ['get', 'color'],
              'circle-stroke-width': 2,
              'circle-stroke-color': '#0F0F1A',
            },
          });

          fitMapToRoute(map, coords, LngLatBounds);
          setMapInteractive(map, mapExpanded);
        } catch (err) {
          console.warn('[GpsTrace] Failed to add route layers', err);
        }

        bumpMapResize();
        map.once('idle', bumpMapResize);
      });

      if (mapContainer) {
        ro = new ResizeObserver(() => map.resize());
        ro.observe(mapContainer);
        bumpMapResize();
      }
    })();

    return () => {
      cancelled = true;
      ro?.disconnect();
      mapInstance?.remove();
      mapInstance = null;
    };
  });

</script>

<svelte:window onkeydown={onWindowKeydown} />

<div class="bg-glass2 border border-border rounded-2xl p-4">
  <p class="text-[11px] font-semibold text-text1 mb-3 font-sans">Route</p>

  {#if routeLatLng.length < 2}
    <div class="text-text2 text-[11px] text-center py-8">No GPS data</div>
  {:else}
    <div class="gps-map-slot {PREVIEW_HEIGHT}" aria-hidden={mapExpanded}>
      <div class="gps-map-shell" class:expanded={mapExpanded}>
        {#if mapExpanded}
          <button
            type="button"
            class="map-backdrop"
            aria-label="Close map"
            onclick={closeMap}
          ></button>
        {/if}

        <div
          class="map-panel"
          class:expanded={mapExpanded}
          role={mapExpanded ? 'dialog' : undefined}
          aria-modal={mapExpanded ? 'true' : undefined}
          aria-label={mapExpanded ? 'Route map' : undefined}
        >
          {#if mapExpanded}
            <button
              type="button"
              class="map-close"
              aria-label="Close map"
              onclick={closeMap}
            >
              ✕
            </button>
          {/if}

          <div
            bind:this={mapContainer}
            class="map-host"
            class:interactive={mapExpanded}
          ></div>

          {#if !mapExpanded}
            <button
              type="button"
              class="explore-overlay"
              aria-label="Expand map"
              onclick={openMap}
            ></button>
          {/if}
        </div>
      </div>
    </div>

    {#if hrMode}
      <div class="mt-2 flex flex-wrap items-center gap-3 text-[10px] font-mono text-text2">
        {#each HR_LEGEND_ZONES as z (z)}
          <span class="inline-flex items-center gap-1.5">
            <span
              class="shrink-0 rounded-full"
              style="width: 8px; height: 8px; background: {ZONE_COLORS[z]};"
            ></span>
            {formatHrZoneTitle(z)}
          </span>
        {/each}
      </div>
    {:else}
      <div class="mt-2 flex flex-wrap items-center gap-3 text-[10px] font-mono text-text2">
        <span class="inline-flex items-center gap-1.5">
          <span class="h-2 w-2 shrink-0 rounded-full bg-teal"></span>
          Start
        </span>
        <span class="inline-flex items-center gap-1.5">
          <span class="h-2 w-2 shrink-0 rounded-full bg-red"></span>
          End
        </span>
      </div>
    {/if}
  {/if}
</div>

<style>
  .gps-map-slot {
    position: relative;
    width: 100%;
  }

  .gps-map-shell {
    position: relative;
    width: 100%;
    height: 100%;
    overflow: hidden;
    border-radius: 1rem;
    border: 1px solid var(--border, rgba(255, 255, 255, 0.07));
    background: var(--bg1, #0f0f1a);
  }

  .gps-map-shell.expanded {
    position: fixed;
    inset: 0;
    z-index: 100;
    width: auto;
    height: auto;
    border-radius: 0;
    border: none;
    overflow: visible;
    background: transparent;
  }

  .map-backdrop {
    position: absolute;
    inset: 0;
    border: none;
    padding: 0;
    margin: 0;
    cursor: pointer;
    background: rgba(8, 8, 15, 0.8);
    display: none;
  }

  @media (min-width: 768px) {
    .map-backdrop {
      display: block;
    }
  }

  .map-panel {
    position: relative;
    width: 100%;
    height: 100%;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    border-radius: inherit;
  }

  .map-panel.expanded {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    width: 100%;
    height: min(92dvh, 100%);
    border-radius: 16px 16px 0 0;
    background: var(--bg1, #0f0f1a);
    border-top: 1px solid var(--border, rgba(255, 255, 255, 0.07));
    transform: translateY(100%);
    transition: transform 0.25s ease;
    z-index: 1;
  }

  .gps-map-shell.expanded .map-panel.expanded {
    transform: translateY(0);
  }

  @media (min-width: 768px) {
    .map-panel.expanded {
      inset: auto;
      top: 50%;
      left: 50%;
      right: auto;
      bottom: auto;
      width: min(720px, 92vw);
      height: min(80vh, 640px);
      border-radius: 16px;
      border: 1px solid var(--border, rgba(255, 255, 255, 0.07));
      transform: translate(-50%, -50%);
      transition: none;
    }

    .gps-map-shell.expanded .map-panel.expanded {
      transform: translate(-50%, -50%);
    }
  }

  .map-close {
    position: absolute;
    top: max(8px, env(safe-area-inset-top, 0px));
    right: 12px;
    width: 36px;
    height: 36px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--border, rgba(255, 255, 255, 0.07));
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.06);
    color: var(--text1, rgba(240, 240, 255, 0.65));
    font-size: 14px;
    cursor: pointer;
    line-height: 1;
    z-index: 2;
  }

  .map-close:hover {
    background: rgba(255, 255, 255, 0.1);
  }

  .map-host {
    flex: 1;
    min-height: 0;
    width: 100%;
    position: relative;
    pointer-events: none;
  }

  .map-host.interactive {
    pointer-events: auto;
  }

  .map-host:not(.interactive) :global(.maplibregl-canvas-container),
  .map-host:not(.interactive) :global(.maplibregl-canvas) {
    pointer-events: none !important;
  }

  .explore-overlay {
    position: absolute;
    inset: 0;
    z-index: 10;
    border: none;
    padding: 0;
    margin: 0;
    cursor: pointer;
    background: transparent;
  }
</style>
