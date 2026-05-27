<script lang="ts">
  import * as d3 from 'd3';
  import { slide } from 'svelte/transition';
  import { formatHrZoneTitle } from '$lib/hrZoneDisplay';
  import {
    cadenceChartTitle,
    cadenceUnitLabel,
    clampPaceSeries,
    coercePaceSport,
    formatPaceAxisTick,
    formatPaceSeconds,
    formatPaceWithSuffix,
    invertedPaceYScale,
    paceChartTitle,
    paceDistanceSuffix,
    paceSecondsFromVelocity,
    speedFromMps,
    speedUnitLabel,
    supportsPaceChart,
    type Units,
  } from '$lib/utils/paceChart';
  import {
    elevationFromMeters,
    elevationUnitLabel,
    formatElevationMeters,
  } from '$lib/utils/units';

  const MIN_SELECTION_SAMPLES = 10;
  const AXIS_TICK_EPSILON = 1e-6;
  const X_AXIS_LABEL_CHAR_PX = 5.5;
  const X_AXIS_LABEL_GAP_PX = 4;
  const METERS_PER_MILE = 1609.344;

  const STREAM_COLORS = {
    heartrate: 'var(--red)',
    pace: 'var(--teal)',
    speed: 'var(--sky)',
    power: 'var(--amber)',
    cadence: 'var(--violet)',
    elevation: 'var(--green)',
  } as const;

  interface Zone {
    zone: number;
    min_bpm: number;
    max_bpm: number;
  }

  interface RangeStats {
    durationSecs: number;
    distanceM: number | null;
    avgHr: number | null;
    maxHr: number | null;
    avgPace: string | null;
    avgWatts: number | null;
    avgCadence: number | null;
    elevGain: number | null;
  }

  let {
    streams,
    laps = [],
    sport = '',
    zones = [],
    measurementUnits = 'metric',
  }: {
    streams: any;
    laps?: any[];
    sport?: string;
    zones?: Zone[];
    measurementUnits?: Units;
  } = $props();

  const zonesSorted = $derived(
    [...zones].sort((a, b) => a.zone - b.zone)
  );

  function getZone(bpm: number): number {
    if (!zonesSorted.length) return 0;
    for (const z of zonesSorted) {
      if (bpm >= z.min_bpm && bpm < z.max_bpm) return z.zone;
    }
    const last = zonesSorted[zonesSorted.length - 1];
    if (last && bpm >= last.min_bpm) return last.zone;
    return 0;
  }

  /** Extra top space so the unit label clears the uppermost y-axis tick (pace/HRV labels need ~12px). */
  const MARGIN = { top: 24, right: 8, bottom: 24, left: 40 };
  const CHART_H = 100;
  const svgH = CHART_H + MARGIN.top + MARGIN.bottom;

  type ChartId = 'hr' | 'pace' | 'speed' | 'cadence' | 'power' | 'elev';

  type ChartModel = {
    id: ChartId;
    title: string;
    unitLabel: string;
    color: string;
    gradientId: string;
    yScale: d3.ScaleLinear<number, number>;
    yTickFormat: (v: d3.NumberValue) => string;
    areaPath: string | null;
    linePath: string | null;
    fillHrArea: boolean;
    stats: {
      subtitle: string;
      hoverLine: (idx: number) => string;
    };
  };

  let chartWidth = $state(300);
  let chartInteractionEl: HTMLDivElement | undefined = $state();
  let hoveredIdx = $state<number | null>(null);
  let hoveredX = $state<number | null>(null);

  let selStartIdx = $state<number | null>(null);
  let selEndIdx = $state<number | null>(null);
  let isDragging = $state(false);
  let dragStartIdx: number | null = null;
  /** Chart row where the user started or is adjusting the selection */
  let interactionChartId = $state<ChartId | null>(null);

  // Single-finger touch scrubbing state
  let touchStartX: number | null = null;
  let touchStartY: number | null = null;
  let isTouchScrubbing = $state(false);

  const hasSelection = $derived(
    selStartIdx !== null &&
      selEndIdx !== null &&
      Math.abs(selEndIdx - selStartIdx) >= MIN_SELECTION_SAMPLES
  );

  let axisXRefs = $state<Partial<Record<ChartId, SVGGElement | undefined>>>({});
  let axisYRefs = $state<Partial<Record<ChartId, SVGGElement | undefined>>>({});

  const ts = $derived(streams?.time_series ?? {});
  const tArr = $derived((ts.time as number[] | undefined) ?? []);
  const hrArr = $derived((ts.heartrate as number[] | undefined) ?? []);
  const velArr = $derived((ts.velocity_smooth as number[] | undefined) ?? []);
  const cadArr = $derived((ts.cadence as number[] | undefined) ?? []);
  const watArr = $derived((ts.watts as number[] | undefined) ?? []);
  const altArr = $derived((ts.altitude as number[] | undefined) ?? []);

  const innerW = $derived(Math.max(1, chartWidth - MARGIN.left - MARGIN.right));
  /** End time in seconds — last index is authoritative for Strava-style streams */
  const tEndSec = $derived(
    Math.max(tArr.length ? (tArr[tArr.length - 1] ?? 0) : 0, d3.max(tArr) ?? 0)
  );
  const xMaxMin = $derived(tEndSec / 60);

  const xScale = $derived(
    d3.scaleLinear<number>().domain([0, xMaxMin || 1]).range([0, innerW])
  );

  function paceAt(i: number): number | null {
    const v = velArr[i];
    if (v == null || !Number.isFinite(v)) return null;
    return paceSecondsFromVelocity(v, sport, measurementUnits);
  }

  function speedAt(i: number): number | null {
    const v = velArr[i];
    if (v == null || !Number.isFinite(v) || v <= 0) return null;
    return speedFromMps(v, measurementUnits);
  }

  function xAxisLabelWidthPx(label: string): number {
    return label.length * X_AXIS_LABEL_CHAR_PX;
  }

  function xAxisTickMinutes(xMax: number, widthPx: number): number[] {
    if (xMax <= 0) return [0];
    const ticks = d3.ticks(0, xMax, 6).filter((t) => t < xMax - AXIS_TICK_EPSILON);
    const finalLabelWidth = xAxisLabelWidthPx(formatXAxisTickMinute(xMax, xMax));
    const spacedTicks = ticks.filter((tick) => {
      const distanceFromFinalPx = ((xMax - tick) / xMax) * widthPx;
      const requiredSpacingPx =
        xAxisLabelWidthPx(formatXAxisTickMinute(tick, xMax)) / 2 +
        finalLabelWidth +
        X_AXIS_LABEL_GAP_PX;

      return distanceFromFinalPx >= requiredSpacingPx;
    });

    return [...spacedTicks, xMax];
  }

  function formatXAxisTickMinute(value: number, xMax: number): string {
    const minutes =
      Math.abs(value - xMax) < AXIS_TICK_EPSILON
        ? Math.ceil(xMax)
        : Math.round(value);
    return `${minutes}m`;
  }

  function plotXFromClientX(clientX: number): number | null {
    const el = chartInteractionEl;
    if (!el || chartWidth <= 0) return null;
    const rect = el.getBoundingClientRect();
    if (rect.width <= 0) return null;
    const frac = (clientX - rect.left) / rect.width;
    const svgX = frac * chartWidth;
    return svgX - MARGIN.left;
  }

  function clientXToIndex(clientX: number): number {
    const px = plotXFromClientX(clientX);
    if (px == null || !tArr.length || innerW <= 0) return 0;
    const clamped = Math.max(0, Math.min(innerW, px));
    const t_sec = xScale.invert(clamped) * 60;
    return Math.min(d3.bisectLeft(tArr, t_sec), tArr.length - 1);
  }

  function formatDuration(secs: number): string {
    const m = Math.floor(secs / 60);
    const s = Math.round(secs % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function formatRangeDistance(m: number): string {
    if (measurementUnits === 'imperial') {
      return `${(m / METERS_PER_MILE).toFixed(2)} mi`;
    }
    return `${(m / 1000).toFixed(2)} km`;
  }

  function paceDivisorM(): number {
    if (coercePaceSport(sport) === 'row') return 500;
    if (measurementUnits === 'imperial') return METERS_PER_MILE;
    return 1000;
  }

  function clearSelection() {
    selStartIdx = null;
    selEndIdx = null;
    interactionChartId = null;
  }

  function chartIdAtClientY(clientY: number): ChartId | null {
    const el = chartInteractionEl;
    if (!el) return null;
    for (const row of el.querySelectorAll<HTMLElement>('[data-chart-row]')) {
      const rect = row.getBoundingClientRect();
      if (clientY >= rect.top && clientY <= rect.bottom) {
        return row.dataset.chartId as ChartId;
      }
    }
    return null;
  }

  const overlayStyle = $derived.by(() => {
    if (!hasSelection || !tArr.length || chartWidth <= 0) return null;
    const x0 = MARGIN.left + xScale(tArr[selStartIdx!] / 60);
    const x1 = MARGIN.left + xScale(tArr[selEndIdx!] / 60);
    const leftPct = ((x0 / chartWidth) * 100).toFixed(3);
    const widthPct = (((x1 - x0) / chartWidth) * 100).toFixed(3);
    return `left: ${leftPct}%; width: ${widthPct}%;`;
  });

  const rangeStats = $derived.by((): RangeStats | null => {
    if (!hasSelection) return null;

    const timeArr = (ts.time as number[] | undefined) ?? [];
    const hrStream = (ts.heartrate as (number | null)[] | undefined) ?? [];
    const distArr = (ts.distance as number[] | undefined) ?? [];
    const wattsStream = (ts.watts as (number | null)[] | undefined) ?? [];
    const cadenceStream = (ts.cadence as (number | null)[] | undefined) ?? [];
    const altStream = (ts.altitude as (number | null)[] | undefined) ?? [];
    const movingArr = (ts.moving as (boolean | null)[] | undefined) ?? [];

    const i0 = selStartIdx!;
    const i1 = selEndIdx!;

    const durationSecs = timeArr.length
      ? (timeArr[Math.min(i1, timeArr.length - 1)] ?? 0) -
        (timeArr[Math.max(i0, 0)] ?? 0)
      : i1 - i0;

    const distanceM = distArr.length
      ? (distArr[Math.min(i1, distArr.length - 1)] ?? 0) -
        (distArr[Math.max(i0, 0)] ?? 0)
      : null;

    function sliceActive<T>(arr: (T | null)[]): T[] {
      const out: T[] = [];
      for (let i = i0; i <= i1 && i < arr.length; i++) {
        const moving = movingArr.length ? movingArr[i] : true;
        if (moving === false) continue;
        const v = arr[i];
        if (v !== null && v !== undefined) out.push(v as T);
      }
      return out;
    }

    const hrSlice = sliceActive(hrStream).filter((v) => (v as number) > 0) as number[];
    const wSlice = sliceActive(wattsStream).filter((v) => (v as number) > 0) as number[];
    const cadSlice = sliceActive(cadenceStream) as number[];

    const avg = (arr: number[]) =>
      arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : null;

    const avgHr = hrSlice.length ? Math.round(avg(hrSlice)!) : null;
    const maxHr = hrSlice.length ? Math.max(...hrSlice) : null;
    const avgWatts = wSlice.length ? Math.round(avg(wSlice)!) : null;
    const avgCadence = cadSlice.length ? Math.round(avg(cadSlice)!) : null;

    let avgPace: string | null = null;
    if (distanceM != null && distanceM > 0 && durationSecs > 0) {
      const divisor = paceDivisorM();
      const secsPerUnit = durationSecs / (distanceM / divisor);
      avgPace = formatPaceSeconds(secsPerUnit);
    }

    let elevGain: number | null = null;
    if (altStream.length) {
      let gain = 0;
      for (let i = i0 + 1; i <= i1 && i < altStream.length; i++) {
        const prev = altStream[i - 1];
        const curr = altStream[i];
        if (prev !== null && curr !== null && curr > prev) gain += curr - prev;
      }
      elevGain = Math.round(gain);
    }

    return {
      durationSecs,
      distanceM,
      avgHr,
      maxHr,
      avgPace,
      avgWatts,
      avgCadence,
      elevGain,
    };
  });

  function onChartPointerDown(e: PointerEvent) {
    if (e.pointerType === 'touch') return;
    interactionChartId = chartIdAtClientY(e.clientY);
    const idx = clientXToIndex(e.clientX);
    dragStartIdx = idx;
    isDragging = true;
    selStartIdx = idx;
    selEndIdx = idx;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  }

  function onChartPointerUpOrCancel(e: PointerEvent) {
    if (isDragging) {
      isDragging = false;
      dragStartIdx = null;
      if (!hasSelection) clearSelection();
    }
    try {
      (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* already released */
    }
  }

  function updateTwoFingerSelection(e: TouchEvent) {
    const midY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
    interactionChartId = chartIdAtClientY(midY) ?? interactionChartId;
    const idxA = clientXToIndex(e.touches[0].clientX);
    const idxB = clientXToIndex(e.touches[1].clientX);
    selStartIdx = Math.min(idxA, idxB);
    selEndIdx = Math.max(idxA, idxB);
  }

  function onTouchStart(e: TouchEvent) {
    // Passive — no preventDefault() here so iOS can start scroll without delay
    if (e.touches.length === 2) {
      updateTwoFingerSelection(e);
      return;
    }
    if (e.touches.length === 1) {
      // Only track touches that begin on a chart row — not on the averages bar or other UI
      const target = e.target as Element;
      if (!target.closest('[data-chart-row]')) return;
      touchStartX = e.touches[0].clientX;
      touchStartY = e.touches[0].clientY;
      isTouchScrubbing = false;
    }
  }

  function onTouchMove(e: TouchEvent) {
    if (e.touches.length === 2) {
      // 2-finger selection: prevent pinch-zoom and scroll
      e.preventDefault();
      updateTwoFingerSelection(e);
      return;
    }
    if (e.touches.length !== 1) return;

    const touch = e.touches[0];

    if (!isTouchScrubbing) {
      if (touchStartX === null || touchStartY === null) return;
      const dx = Math.abs(touch.clientX - touchStartX);
      const dy = Math.abs(touch.clientY - touchStartY);
      // Wait for 8px of movement and require clearly horizontal before committing
      if (dx < 8 && dy < 8) return;
      if (dx > dy * 1.5) {
        isTouchScrubbing = true;
      } else {
        // Vertical intent — let scroll win, stop tracking this gesture
        touchStartX = null;
        touchStartY = null;
        return;
      }
    }

    // Committed to horizontal scrub: block scroll and drive the crosshair
    e.preventDefault();
    const idx = clientXToIndex(touch.clientX);
    hoveredIdx = idx;
    const px = plotXFromClientX(touch.clientX);
    if (px != null && tArr.length && innerW > 0) {
      hoveredX = xScale(tArr[Math.min(idx, tArr.length - 1)] / 60);
    }
  }

  function onTouchEnd() {
    if (isTouchScrubbing) {
      isTouchScrubbing = false;
      hoveredIdx = null;
      hoveredX = null;
    }
    touchStartX = null;
    touchStartY = null;
  }

  const chartModels = $derived.by((): ChartModel[] => {
    if (tArr.length < 2 || innerW <= 0) return [];
    const xS = xScale;
    const list: ChartModel[] = [];

    if (hrArr.length > 1) {
      const hrs = hrArr
        .map((h) => (h != null && Number.isFinite(h) ? h : null))
        .filter((h): h is number => h != null);
      let yMin = d3.min(hrs) ?? 0;
      let yMax = d3.max(hrs) ?? 1;
      const pad = Math.max(4, (yMax - yMin) * 0.08);
      yMin -= pad;
      yMax += pad;
      const yS = d3.scaleLinear().domain([yMin, yMax]).range([CHART_H, 0]);

      const areaGen = d3
        .area<number>()
        .x((_, i) => xS(tArr[i] / 60))
        .y0(yS(yMin))
        .y1((v) => yS(v))
        .defined((v, i) => v != null && Number.isFinite(v))
        .curve(d3.curveMonotoneX);

      const areaPath = areaGen(hrArr) as string | null;

      /** One continuous stroke — per-zone spline segments distort at boundaries (flattened “rails” near BPM thresholds). */
      const lineGen = d3
        .line<number>()
        .x((_, i) => xS(tArr[i] / 60))
        .y((v) => yS(v))
        .defined((v) => v != null && Number.isFinite(v))
        .curve(d3.curveMonotoneX);

      const linePath = lineGen(hrArr) as string | null;

      const avg =
        hrs.reduce((a, b) => a + b, 0) / Math.max(1, hrs.length);
      const max = d3.max(hrs) ?? 0;

      list.push({
        id: 'hr',
        title: 'Heart Rate',
        unitLabel: 'bpm',
        color: STREAM_COLORS.heartrate,
        gradientId: 'grad-hr',
        yScale: yS,
        yTickFormat: (v) => String(Math.round(Number(v))),
        areaPath,
        linePath,
        fillHrArea: true,
        stats: {
          subtitle: `Avg ${Math.round(avg)} bpm · Max ${Math.round(max)} bpm`,
          hoverLine: (idx: number) => {
            const hb = hrArr[idx];
            if (hb == null || !Number.isFinite(hb)) return '';
            const z = getZone(hb);
            const segment = z > 0 ? formatHrZoneTitle(z) : 'Outside zones';
            return `${Math.round(tArr[idx] / 60)}m · ${Math.round(hb)} bpm · ${segment}`;
          },
        },
      });
    }

    if (velArr.length > 1 && supportsPaceChart(sport)) {
      const paceVals = tArr.map((_, i) => paceAt(i));
      const pValid = paceVals.filter((v): v is number => v != null);
      if (pValid.length > 1) {
        const { lo: pLo, hi: pHi } = clampPaceSeries(pValid);
        const yS = invertedPaceYScale(pLo, pHi, CHART_H);
        /** Stopped / bad velocity: pin to slow (top) edge on inverted axis */
        const paceFloor = pHi;
        const paceDisplay = tArr.map((_, i) => {
          const p = paceAt(i);
          if (p == null) return paceFloor;
          return Math.min(pHi, Math.max(pLo, p));
        });

        const areaGen = d3
          .area<number>()
          .x((_, i) => xS(tArr[i] / 60))
          .y0(CHART_H)
          .y1((v) => yS(v))
          .curve(d3.curveMonotoneX);

        const lineGen = d3
          .line<number>()
          .x((_, i) => xS(tArr[i] / 60))
          .y((v) => yS(v))
          .curve(d3.curveMonotoneX);

        const best = d3.min(pValid) ?? 0;
        const avg = pValid.reduce((a, b) => a + b, 0) / pValid.length;
        const paceSuffix = paceDistanceSuffix(sport, measurementUnits);

        list.push({
          id: 'pace',
          title: paceChartTitle(sport, measurementUnits),
          unitLabel: paceSuffix,
          color: STREAM_COLORS.pace,
          gradientId: 'grad-pace',
          yScale: yS,
          yTickFormat: formatPaceAxisTick,
          areaPath: areaGen(paceDisplay),
          linePath: lineGen(paceDisplay),
          fillHrArea: false,
          stats: {
            subtitle: `Best ${formatPaceWithSuffix(best, sport, measurementUnits)} · Avg ${formatPaceWithSuffix(avg, sport, measurementUnits)}`,
            hoverLine: (idx: number) => {
              const p = paceDisplay[idx];
              return `${Math.round(tArr[idx] / 60)}m · ${formatPaceWithSuffix(p, sport, measurementUnits)}`;
            },
          },
        });
      }
    }

    if (velArr.length > 1) {
      const spdVals = tArr.map((_, i) => speedAt(i));
      const sValid = spdVals.filter((v): v is number => v != null);
      if (sValid.length > 1) {
        let yMin = d3.min(sValid) ?? 0;
        let yMax = d3.max(sValid) ?? 1;
        const pad = Math.max(0.5, (yMax - yMin) * 0.08);
        yMin = Math.max(0, yMin - pad);
        yMax += pad;
        const yS = d3.scaleLinear().domain([yMin, yMax]).range([CHART_H, 0]);
        const areaGen = d3
          .area<number | null>()
          .x((_, i) => xS(tArr[i] / 60))
          .y0(yS(yMin))
          .y1((v) => yS(v as number))
          .defined((v) => v != null)
          .curve(d3.curveMonotoneX);
        const lineGen = d3
          .line<number | null>()
          .x((_, i) => xS(tArr[i] / 60))
          .y((v) => yS(v as number))
          .defined((v) => v != null)
          .curve(d3.curveMonotoneX);
        const mx = d3.max(sValid) ?? 0;
        const av = sValid.reduce((a, b) => a + b, 0) / sValid.length;
        const speedUnit = speedUnitLabel(measurementUnits);

        list.push({
          id: 'speed',
          title: `Speed ${speedUnit}`,
          unitLabel: speedUnit,
          color: STREAM_COLORS.speed,
          gradientId: 'grad-speed',
          yScale: yS,
          yTickFormat: (v) => String(Math.round(Number(v))),
          areaPath: areaGen(spdVals),
          linePath: lineGen(spdVals),
          fillHrArea: false,
          stats: {
            subtitle: `Max ${mx.toFixed(1)} ${speedUnit} · Avg ${av.toFixed(1)} ${speedUnit}`,
            hoverLine: (idx: number) => {
              const s = speedAt(idx);
              if (s == null) return '';
              return `${Math.round(tArr[idx] / 60)}m · ${s.toFixed(1)} ${speedUnit}`;
            },
          },
        });
      }
    }

    if (cadArr.length > 1) {
      const cadVals = tArr.map((_, i) => {
        const c = cadArr[i];
        if (c == null || !Number.isFinite(c)) return null;
        return c;
      });
      const cValid = cadVals.filter((v): v is number => v != null);
      if (cValid.length > 1) {
        let yMin = d3.min(cValid) ?? 0;
        let yMax = d3.max(cValid) ?? 1;
        const pad = Math.max(1, (yMax - yMin) * 0.08);
        yMin -= pad;
        yMax += pad;
        const yS = d3.scaleLinear().domain([yMin, yMax]).range([CHART_H, 0]);
        const areaGen = d3
          .area<number | null>()
          .x((_, i) => xS(tArr[i] / 60))
          .y0(yS(yMin))
          .y1((v) => yS(v as number))
          .defined((v) => v != null)
          .curve(d3.curveMonotoneX);
        const lineGen = d3
          .line<number | null>()
          .x((_, i) => xS(tArr[i] / 60))
          .y((v) => yS(v as number))
          .defined((v) => v != null)
          .curve(d3.curveMonotoneX);
        const av = cValid.reduce((a, b) => a + b, 0) / cValid.length;
        const unit = cadenceUnitLabel(sport);
        list.push({
          id: 'cadence',
          title: cadenceChartTitle(sport),
          unitLabel: unit,
          color: STREAM_COLORS.cadence,
          gradientId: 'grad-cadence',
          yScale: yS,
          yTickFormat: (v) => String(Math.round(Number(v))),
          areaPath: areaGen(cadVals),
          linePath: lineGen(cadVals),
          fillHrArea: false,
          stats: {
            subtitle: `Avg ${av.toFixed(0)} ${unit}`,
            hoverLine: (idx: number) => {
              const c = cadVals[idx];
              if (c == null) return '';
              return `${Math.round(tArr[idx] / 60)}m · ${Math.round(c)} ${unit}`;
            },
          },
        });
      }
    }

    if (watArr.length > 1) {
      const wVals = tArr.map((_, i) => {
        const w = watArr[i];
        if (w == null || !Number.isFinite(w)) return null;
        return w;
      });
      const wValid = wVals.filter((v): v is number => v != null);
      if (wValid.length > 1) {
        let yMin = 0;
        let yMax = d3.max(wValid) ?? 1;
        const pad = Math.max(10, yMax * 0.05);
        yMax += pad;
        const yS = d3.scaleLinear().domain([yMin, yMax]).range([CHART_H, 0]);
        const areaGen = d3
          .area<number | null>()
          .x((_, i) => xS(tArr[i] / 60))
          .y0(yS(yMin))
          .y1((v) => yS(v as number))
          .defined((v) => v != null)
          .curve(d3.curveMonotoneX);
        const lineGen = d3
          .line<number | null>()
          .x((_, i) => xS(tArr[i] / 60))
          .y((v) => yS(v as number))
          .defined((v) => v != null)
          .curve(d3.curveMonotoneX);
        const mx = d3.max(wValid) ?? 0;
        const av = wValid.reduce((a, b) => a + b, 0) / wValid.length;

        list.push({
          id: 'power',
          title: 'Power',
          unitLabel: 'W',
          color: STREAM_COLORS.power,
          gradientId: 'grad-power',
          yScale: yS,
          yTickFormat: (v) => String(Math.round(Number(v))),
          areaPath: areaGen(wVals),
          linePath: lineGen(wVals),
          fillHrArea: false,
          stats: {
            subtitle: `Avg ${av.toFixed(0)} W · Max ${Math.round(mx)} W`,
            hoverLine: (idx: number) => {
              const w = wVals[idx];
              if (w == null) return '';
              return `${Math.round(tArr[idx] / 60)}m · ${Math.round(w)} W`;
            },
          },
        });
      }
    }

    if (altArr.length > 1) {
      const aVals = tArr.map((_, i) => {
        const a = altArr[i];
        if (a == null || !Number.isFinite(a)) return null;
        return a;
      });
      const aValid = aVals.filter((v): v is number => v != null);
      const elevRange =
        aValid.length > 1 ? (d3.max(aValid) ?? 0) - (d3.min(aValid) ?? 0) : 0;
      if (aValid.length > 1 && elevRange >= 1) {
        const elevDisplay = aValid.map((m) => elevationFromMeters(m, measurementUnits));
        const elevRangeDisplay =
          (d3.max(elevDisplay) ?? 0) - (d3.min(elevDisplay) ?? 0);
        const elevMinM = d3.min(aValid) ?? 0;
        const elevMaxM = d3.max(aValid) ?? 0;
        if (elevRangeDisplay >= (measurementUnits === 'imperial' ? 3 : 1)) {
          let yMin = d3.min(elevDisplay) ?? 0;
          let yMax = d3.max(elevDisplay) ?? 1;
          const pad = Math.max(1, (yMax - yMin) * 0.08);
          yMin -= pad;
          yMax += pad;
          const yS = d3.scaleLinear().domain([yMin, yMax]).range([CHART_H, 0]);
          const elevSeries = tArr.map((_, i) => {
            const a = altArr[i];
            if (a == null || !Number.isFinite(a)) return null;
            return elevationFromMeters(a, measurementUnits);
          });
          const areaGen = d3
            .area<number | null>()
            .x((_, i) => xS(tArr[i] / 60))
            .y0(yS(yMin))
            .y1((v) => yS(v as number))
            .defined((v) => v != null)
            .curve(d3.curveMonotoneX);
          const lineGen = d3
            .line<number | null>()
            .x((_, i) => xS(tArr[i] / 60))
            .y((v) => yS(v as number))
            .defined((v) => v != null)
            .curve(d3.curveMonotoneX);
          const elevUnit = elevationUnitLabel(measurementUnits);

          list.push({
            id: 'elev',
            title: 'Elevation',
            unitLabel: elevUnit,
            color: STREAM_COLORS.elevation,
            gradientId: 'grad-elev',
            yScale: yS,
            yTickFormat: (v) => String(Math.round(Number(v))),
            areaPath: areaGen(elevSeries),
            linePath: lineGen(elevSeries),
            fillHrArea: false,
            stats: {
              subtitle: `Min ${formatElevationMeters(elevMinM, measurementUnits)} · Max ${formatElevationMeters(elevMaxM, measurementUnits)}`,
              hoverLine: (idx: number) => {
                const a = altArr[idx];
                if (a == null || !Number.isFinite(a)) return '';
                return `${Math.round(tArr[idx] / 60)}m · ${formatElevationMeters(a, measurementUnits)}`;
              },
            },
          });
        }
      }
    }

    return list;
  });

  $effect(() => {
    if (!chartInteractionEl) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) chartWidth = w;
    });
    ro.observe(chartInteractionEl);
    chartWidth = chartInteractionEl.clientWidth || 300;
    return () => ro.disconnect();
  });

  $effect(() => {
    const el = chartInteractionEl;
    if (!el) return;
    const onStart = (e: TouchEvent) => onTouchStart(e);
    const onMove = (e: TouchEvent) => onTouchMove(e);
    const onEnd = () => onTouchEnd();
    // touchstart passive: lets iOS begin scroll immediately without waiting for JS
    // touchmove non-passive: we may call preventDefault() for horizontal scrub
    el.addEventListener('touchstart', onStart, { passive: true });
    el.addEventListener('touchmove', onMove, { passive: false });
    el.addEventListener('touchend', onEnd);
    el.addEventListener('touchcancel', onEnd);
    return () => {
      el.removeEventListener('touchstart', onStart);
      el.removeEventListener('touchmove', onMove);
      el.removeEventListener('touchend', onEnd);
      el.removeEventListener('touchcancel', onEnd);
    };
  });

  function onChartPointerMove(e: PointerEvent) {
    if (isDragging && dragStartIdx !== null) {
      interactionChartId = chartIdAtClientY(e.clientY) ?? interactionChartId;
      const idx = clientXToIndex(e.clientX);
      selStartIdx = Math.min(dragStartIdx, idx);
      selEndIdx = Math.max(dragStartIdx, idx);
      return;
    }

    const px = plotXFromClientX(e.clientX);
    if (px == null || !tArr.length || innerW <= 0) return;
    if (px < 0 || px > innerW) {
      hoveredIdx = null;
      hoveredX = null;
      return;
    }
    const t_min = xScale.invert(px);
    const t_sec = t_min * 60;
    const bisect = d3.bisectLeft(tArr, t_sec);
    const idx = Math.min(bisect, tArr.length - 1);
    hoveredIdx = idx;
    hoveredX = xScale(tArr[idx] / 60);
  }

  function onChartPointerLeave() {
    hoveredIdx = null;
    hoveredX = null;
  }

  $effect(() => {
    axisXRefs;
    axisYRefs;
    const xs = xScale;
    const xMax = xMaxMin;
    for (const c of chartModels) {
      const gx = axisXRefs[c.id];
      if (gx) {
        const ticks = xAxisTickMinutes(xMax, innerW);
        const axis = d3
          .axisBottom(xs)
          .tickValues(ticks)
          .tickFormat((d) => formatXAxisTickMinute(Number(d), xMax))
          .tickSize(3)
          .tickSizeOuter(0);
        const sel = d3.select(gx);
        sel.call(axis);
        sel.select('.domain').remove();
        sel
          .selectAll('.tick line')
          .attr('stroke', 'var(--border)')
          .attr('stroke-opacity', 0.5);
        sel
          .selectAll('.tick text')
          .attr('font-size', 9)
          .attr('font-family', 'monospace')
          .attr('fill', 'var(--text2)');
        sel.selectAll<SVGGElement, number>('.tick').each(function (_, i, nodes) {
          const text = d3.select(this).select('text');
          if (i === 0) {
            text.attr('text-anchor', 'start');
          } else if (i === nodes.length - 1) {
            text.attr('text-anchor', 'end');
          } else {
            text.attr('text-anchor', 'middle');
          }
        });
      }

      const gy = axisYRefs[c.id];
      if (gy) {
        const axis = d3
          .axisLeft(c.yScale)
          .ticks(4)
          .tickFormat(c.yTickFormat)
          .tickSize(0)
          .tickSizeOuter(0);
        const sel = d3.select(gy);
        sel.call(axis);
        sel.select('.domain').remove();
        sel
          .selectAll('.tick text')
          .attr('dx', -6)
          .attr('font-size', 9)
          .attr('font-family', 'monospace')
          .attr('fill', 'var(--text2)');
      }
    }
  });

</script>

<div class="rounded-2xl bg-glass2 border border-border p-3 space-y-4">
  <p class="text-[11px] font-semibold text-text1 flex items-center gap-1.5">
    <span class="w-1.5 h-1.5 rounded-full bg-teal inline-block"></span>
    Activity Streams
  </p>

  {#if chartModels.length === 0}
    <p class="text-[12px] text-text2 font-mono text-center py-6">
      Stream data unavailable for this workout.
    </p>
  {:else}
    <div
      class="chart-interaction-wrapper space-y-3"
      style="touch-action: {isDragging || isTouchScrubbing ? 'none' : 'pan-y'};"
      bind:this={chartInteractionEl}
      onpointerdown={onChartPointerDown}
      onpointermove={onChartPointerMove}
      onpointerup={onChartPointerUpOrCancel}
      onpointercancel={onChartPointerUpOrCancel}
      onpointerleave={onChartPointerLeave}
      role="presentation"
    >
      {#each chartModels as c (c.id)}
      <div
        data-chart-row
        data-chart-id={c.id}
        class="relative"
      >
        <p class="text-[11px] font-semibold text-text0 mb-0.5">{c.title}</p>
        <p class="text-[10px] font-mono text-text2 h-4 mb-0.5">
          {hoveredIdx === null ? c.stats.subtitle : c.stats.hoverLine(hoveredIdx)}
        </p>
        <svg
          class="pointer-events-none block w-full"
          width="100%"
          height={svgH}
          viewBox="0 0 {chartWidth} {svgH}"
          preserveAspectRatio="none"
        >
          <defs>
            <linearGradient
              id={c.gradientId}
              x1="0"
              y1="0"
              x2="0"
              y2="1"
            >
              <stop
                offset="0%"
                stop-color={c.color}
                stop-opacity={c.fillHrArea ? 0.15 : 0.25}
              />
              <stop
                offset="100%"
                stop-color={c.color}
                stop-opacity="0"
              />
            </linearGradient>
          </defs>

          <text
            x={6}
            y={MARGIN.top - 14}
            text-anchor="start"
            font-size="9"
            fill="var(--text2)"
            font-family="monospace"
          >
            {c.unitLabel}
          </text>

          <g transform="translate({MARGIN.left},{MARGIN.top})">
            {#if c.areaPath}
              <path
                d={c.areaPath}
                fill={`url(#${c.gradientId})`}
                stroke="none"
              />
            {/if}

            {#if c.linePath}
              <path
                d={c.linePath}
                fill="none"
                stroke={c.color}
                stroke-width="1.5"
              />
            {/if}

            {#if hoveredIdx !== null && hoveredX !== null}
              <line
                x1={hoveredX}
                x2={hoveredX}
                y1="0"
                y2={CHART_H}
                stroke="white"
                stroke-opacity="0.15"
                stroke-width="1"
                pointer-events="none"
              />
            {/if}
          </g>

          <g
            bind:this={axisXRefs[c.id]}
            transform="translate({MARGIN.left},{MARGIN.top + CHART_H})"
          ></g>
          <g
            bind:this={axisYRefs[c.id]}
            transform="translate({MARGIN.left},{MARGIN.top})"
          ></g>
        </svg>
      </div>

      {#if hasSelection && rangeStats && interactionChartId === c.id}
        <div
          class="relative z-30 flex items-center gap-1.5 mt-2 px-2.5 py-2 bg-bg2 border border-white/[0.12] rounded-xl overflow-x-auto touch-pan-y"
          transition:slide={{ duration: 200, axis: 'y' }}
        >
            <div class="flex gap-1.5 flex-1 overflow-x-auto">
              <div class="flex flex-col items-center px-2.5 py-1 bg-white/[0.07] rounded-lg shrink-0">
                <span class="font-mono text-[9px] uppercase tracking-widest text-white/[0.45] mb-0.5"
                  >Duration</span
                >
                <span class="font-mono text-[13px] font-bold tabular-nums text-text0"
                  >{formatDuration(rangeStats.durationSecs)}</span
                >
              </div>

              {#if rangeStats.distanceM !== null}
                <div class="flex flex-col items-center px-2.5 py-1 bg-white/[0.07] rounded-lg shrink-0">
                  <span class="font-mono text-[9px] uppercase tracking-widest text-white/[0.45] mb-0.5"
                    >Dist</span
                  >
                  <span class="font-mono text-[13px] font-bold tabular-nums text-text0"
                    >{formatRangeDistance(rangeStats.distanceM)}</span
                  >
                </div>
              {/if}

              {#if rangeStats.avgPace !== null}
                <div class="flex flex-col items-center px-2.5 py-1 bg-white/[0.07] rounded-lg shrink-0">
                  <span class="font-mono text-[9px] uppercase tracking-widest text-white/[0.45] mb-0.5"
                    >Avg pace</span
                  >
                  <span class="font-mono text-[13px] font-bold tabular-nums text-text0"
                    >{rangeStats.avgPace}{paceDistanceSuffix(sport, measurementUnits)}</span
                  >
                </div>
              {/if}

              {#if rangeStats.avgHr !== null}
                <div class="flex flex-col items-center px-2.5 py-1 bg-white/[0.07] rounded-lg shrink-0">
                  <span class="font-mono text-[9px] uppercase tracking-widest text-white/[0.45] mb-0.5"
                    >Avg HR</span
                  >
                  <span class="font-mono text-[13px] font-bold tabular-nums text-text0">
                    {rangeStats.avgHr}
                    <span class="text-[10px] font-normal text-text2">bpm</span>
                  </span>
                </div>
              {/if}

              {#if rangeStats.maxHr !== null}
                <div class="flex flex-col items-center px-2.5 py-1 bg-white/[0.07] rounded-lg shrink-0">
                  <span class="font-mono text-[9px] uppercase tracking-widest text-white/[0.45] mb-0.5"
                    >Max HR</span
                  >
                  <span class="font-mono text-[13px] font-bold tabular-nums text-text0">
                    {rangeStats.maxHr}
                    <span class="text-[10px] font-normal text-text2">bpm</span>
                  </span>
                </div>
              {/if}

              {#if rangeStats.avgWatts !== null}
                <div class="flex flex-col items-center px-2.5 py-1 bg-white/[0.07] rounded-lg shrink-0">
                  <span class="font-mono text-[9px] uppercase tracking-widest text-white/[0.45] mb-0.5"
                    >Avg power</span
                  >
                  <span class="font-mono text-[13px] font-bold tabular-nums text-text0">
                    {rangeStats.avgWatts}
                    <span class="text-[10px] font-normal text-text2">W</span>
                  </span>
                </div>
              {/if}

              {#if rangeStats.avgCadence !== null}
                <div class="flex flex-col items-center px-2.5 py-1 bg-white/[0.07] rounded-lg shrink-0">
                  <span class="font-mono text-[9px] uppercase tracking-widest text-white/[0.45] mb-0.5"
                    >Cadence</span
                  >
                  <span class="font-mono text-[13px] font-bold tabular-nums text-text0">
                    {rangeStats.avgCadence}
                    <span class="text-[10px] font-normal text-text2"
                      >{cadenceUnitLabel(sport)}</span
                    >
                  </span>
                </div>
              {/if}

              {#if rangeStats.elevGain !== null && rangeStats.elevGain > 0}
                <div class="flex flex-col items-center px-2.5 py-1 bg-white/[0.07] rounded-lg shrink-0">
                  <span class="font-mono text-[9px] uppercase tracking-widest text-white/[0.45] mb-0.5"
                    >Elev gain</span
                  >
                  <span class="font-mono text-[13px] font-bold tabular-nums text-text0">
                    {rangeStats.elevGain}
                    <span class="text-[10px] font-normal text-text2">m</span>
                  </span>
                </div>
              {/if}
            </div>

            <button
              type="button"
              class="shrink-0 text-text2 hover:text-text1 hover:bg-white/[0.07] rounded-md px-1.5 py-1 text-sm leading-none transition-colors"
              onclick={clearSelection}
              aria-label="Clear selection"
            >
              ✕
            </button>
          </div>
        {/if}
    {/each}

      {#if overlayStyle}
        <div
          class="absolute top-0 bottom-0 pointer-events-none z-10 bg-white/[0.07] border-l-2 border-r-2 border-white/30"
          style={overlayStyle}
          aria-hidden="true"
        ></div>
      {/if}
    </div>
  {/if}
</div>

<style>
  .chart-interaction-wrapper {
    position: relative;
    isolation: isolate;
    user-select: none;
    -webkit-user-select: none;
  }

</style>
