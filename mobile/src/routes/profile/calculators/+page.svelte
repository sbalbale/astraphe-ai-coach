<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import { goto } from '$app/navigation';

  function goBack() {
    goto('/profile');
  }

  function finite(n: number) {
    return Number.isFinite(n) ? n : null;
  }

  function pad2(n: number) {
    return String(Math.floor(n)).padStart(2, '0');
  }

  function formatHms(totalSeconds: number) {
    const s = Math.max(0, Math.round(totalSeconds));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    return h > 0 ? `${h}:${pad2(m)}:${pad2(sec)}` : `${m}:${pad2(sec)}`;
  }

  function formatPaceMinutesPerKm(minutesPerKm: number) {
    const sec = Math.round(minutesPerKm * 60);
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${pad2(s)}/km`;
  }

  // --- Race predictor (Riegel) ---
  let baseDistanceKm = $state<number | ''>('');
  let baseTimeMin = $state<number | ''>('');
  let targetDistanceKm = $state<number | ''>('');

  const riegelSeconds = $derived.by(() => {
    const d1 = typeof baseDistanceKm === 'number' ? baseDistanceKm : NaN;
    const t1min = typeof baseTimeMin === 'number' ? baseTimeMin : NaN;
    const d2 = typeof targetDistanceKm === 'number' ? targetDistanceKm : NaN;
    if (!(d1 > 0) || !(t1min > 0) || !(d2 > 0)) return null;
    const t1 = t1min * 60;
    const t2 = t1 * Math.pow(d2 / d1, 1.06);
    return finite(t2);
  });

  const riegelPace = $derived.by(() => {
    if (!riegelSeconds || !(typeof targetDistanceKm === 'number' && targetDistanceKm > 0)) return null;
    return finite((riegelSeconds / 60) / targetDistanceKm);
  });

  // --- VMA calculator ---
  type FractionPreset = { label: string; value: number };
  const presets: FractionPreset[] = [
    { label: '3k (0.95)', value: 0.95 },
    { label: '5k (0.90)', value: 0.9 },
    { label: '10k (0.88)', value: 0.88 },
    { label: 'Half (0.85)', value: 0.85 },
    { label: 'Marathon (0.83)', value: 0.83 }
  ];

  let vmaDistanceKm = $state<number | ''>('');
  let vmaTimeMin = $state<number | ''>('');
  let fractionMode = $state<'preset' | 'custom'>('preset');
  let fractionPreset = $state(presets[0].value);
  let fractionCustom = $state<number | ''>('');

  const fraction = $derived.by(() => {
    const f =
      fractionMode === 'preset'
        ? fractionPreset
        : typeof fractionCustom === 'number'
          ? fractionCustom
          : NaN;
    if (!(f > 0) || !(f <= 1.2)) return null;
    return finite(f);
  });

  const vmaKmh = $derived.by(() => {
    const d = typeof vmaDistanceKm === 'number' ? vmaDistanceKm : NaN;
    const tmin = typeof vmaTimeMin === 'number' ? vmaTimeMin : NaN;
    if (!(d > 0) || !(tmin > 0) || !fraction) return null;
    const hours = tmin / 60;
    const speed = d / hours; // km/h
    const vma = speed / fraction;
    return finite(vma);
  });

  const vmaMs = $derived.by(() => (vmaKmh ? finite(vmaKmh / 3.6) : null));
  const vmaPace = $derived.by(() => (vmaKmh ? finite(60 / vmaKmh) : null));
</script>

<div class="flex flex-col gap-3">
  <div class="flex items-center gap-3">
    <button
      onclick={goBack}
      class="w-8 h-8 flex items-center justify-center bg-glass border border-border rounded-lg text-text2 hover:text-text0 transition-colors cursor-pointer"
    >
      ←
    </button>
    <div>
      <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Account</p>
      <h1 class="text-[22px] font-bold tracking-[-0.02em]">Pacing &amp; VMA</h1>
    </div>
  </div>

  <div class="flex flex-col gap-3 mt-2">
    <Card>
      <p class="text-[13px] font-semibold mb-3">Race Predictor (Riegel)</p>

      <div class="grid grid-cols-3 gap-2">
        <div class="flex flex-col gap-1">
          <p class="text-[10px] text-text2 uppercase tracking-wider">Baseline Distance</p>
          <input
            type="number"
            min="0"
            step="0.1"
            placeholder="km"
            bind:value={baseDistanceKm}
            class="w-full p-2 rounded-xl bg-glass border border-border text-[13px] text-text0 outline-none"
          />
        </div>

        <div class="flex flex-col gap-1">
          <p class="text-[10px] text-text2 uppercase tracking-wider">Baseline Time</p>
          <input
            type="number"
            min="0"
            step="0.1"
            placeholder="minutes"
            bind:value={baseTimeMin}
            class="w-full p-2 rounded-xl bg-glass border border-border text-[13px] text-text0 outline-none"
          />
        </div>

        <div class="flex flex-col gap-1">
          <p class="text-[10px] text-text2 uppercase tracking-wider">Target Distance</p>
          <input
            type="number"
            min="0"
            step="0.1"
            placeholder="km"
            bind:value={targetDistanceKm}
            class="w-full p-2 rounded-xl bg-glass border border-border text-[13px] text-text0 outline-none"
          />
        </div>
      </div>

      <div class="mt-4 p-3 rounded-xl bg-glass border border-border">
        <p class="text-[11px] text-text2 uppercase tracking-wider">Predicted</p>
        {#if riegelSeconds}
          <div class="mt-1 flex items-baseline justify-between gap-3 flex-wrap">
            <p class="text-[18px] font-semibold font-mono text-astrape-teal">{formatHms(riegelSeconds)}</p>
            {#if riegelPace}
              <p class="text-[13px] font-semibold font-mono text-blue">{formatPaceMinutesPerKm(riegelPace)}</p>
            {/if}
          </div>
        {:else}
          <p class="mt-1 text-[13px] text-text2">Enter baseline + target to predict.</p>
        {/if}
      </div>
    </Card>

    <Card>
      <p class="text-[13px] font-semibold mb-3">VMA Calculator</p>

      <div class="grid grid-cols-3 gap-2">
        <div class="flex flex-col gap-1">
          <p class="text-[10px] text-text2 uppercase tracking-wider">Distance</p>
          <input
            type="number"
            min="0"
            step="0.1"
            placeholder="km"
            bind:value={vmaDistanceKm}
            class="w-full p-2 rounded-xl bg-glass border border-border text-[13px] text-text0 outline-none"
          />
        </div>

        <div class="flex flex-col gap-1">
          <p class="text-[10px] text-text2 uppercase tracking-wider">Time</p>
          <input
            type="number"
            min="0"
            step="0.1"
            placeholder="minutes"
            bind:value={vmaTimeMin}
            class="w-full p-2 rounded-xl bg-glass border border-border text-[13px] text-text0 outline-none"
          />
        </div>

        <div class="flex flex-col gap-1">
          <p class="text-[10px] text-text2 uppercase tracking-wider">Fraction</p>
          <div class="flex gap-2">
            <button
              type="button"
              class="px-2 py-2 rounded-xl bg-glass border text-[11px] font-medium transition-colors cursor-pointer {fractionMode === 'preset'
                ? 'text-text0 border-teal/40'
                : 'text-text2 border-border'}"
              onclick={() => (fractionMode = 'preset')}
            >
              Preset
            </button>
            <button
              type="button"
              class="px-2 py-2 rounded-xl bg-glass border text-[11px] font-medium transition-colors cursor-pointer {fractionMode === 'custom'
                ? 'text-text0 border-blue/40'
                : 'text-text2 border-border'}"
              onclick={() => (fractionMode = 'custom')}
            >
              Custom
            </button>
          </div>
        </div>
      </div>

      <div class="mt-2">
        {#if fractionMode === 'preset'}
          <select
            bind:value={fractionPreset}
            class="w-full p-2 rounded-xl bg-glass border border-border text-[13px] text-text0 outline-none"
          >
            {#each presets as p (p.value)}
              <option value={p.value}>{p.label}</option>
            {/each}
          </select>
        {:else}
          <input
            type="number"
            min="0"
            max="1.2"
            step="0.01"
            placeholder="e.g. 0.90"
            bind:value={fractionCustom}
            class="w-full p-2 rounded-xl bg-glass border border-border text-[13px] text-text0 outline-none"
          />
        {/if}
      </div>

      <div class="mt-4 p-3 rounded-xl bg-glass border border-border">
        <p class="text-[11px] text-text2 uppercase tracking-wider">Result</p>
        {#if vmaKmh && vmaMs}
          <div class="mt-1 grid grid-cols-2 gap-2">
            <div class="p-3 rounded-xl bg-glass border border-border">
              <p class="text-[10px] text-text2 uppercase tracking-wider">VMA</p>
              <p class="mt-1 text-[16px] font-semibold font-mono text-astrape-teal">{vmaKmh.toFixed(2)} km/h</p>
              <p class="text-[12px] font-semibold font-mono text-blue">{vmaMs.toFixed(2)} m/s</p>
            </div>
            <div class="p-3 rounded-xl bg-glass border border-border">
              <p class="text-[10px] text-text2 uppercase tracking-wider">Pace @ VMA</p>
              {#if vmaPace}
                <p class="mt-1 text-[16px] font-semibold font-mono text-astrape-teal">{formatPaceMinutesPerKm(vmaPace)}</p>
              {:else}
                <p class="mt-1 text-[13px] text-text2">—</p>
              {/if}
            </div>
          </div>
        {:else}
          <p class="mt-1 text-[13px] text-text2">Enter distance + time + fraction.</p>
        {/if}
      </div>
    </Card>
  </div>
</div>
