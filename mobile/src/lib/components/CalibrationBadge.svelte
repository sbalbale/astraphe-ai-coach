<script lang="ts">
  import { onMount } from 'svelte';

  let showTooltip = $state(false);
  let badgeEl = $state<HTMLElement | null>(null);

  function toggleTooltip(e: MouseEvent | TouchEvent) {
    e.stopPropagation();
    showTooltip = !showTooltip;
  }

  // Handle clicking outside to close tooltip
  function handleClickOutside(e: MouseEvent) {
    if (showTooltip && badgeEl && !badgeEl.contains(e.target as Node)) {
      showTooltip = false;
    }
  }

  onMount(() => {
    window.addEventListener('click', handleClickOutside);
    return () => window.removeEventListener('click', handleClickOutside);
  });
</script>

<button 
  bind:this={badgeEl}
  class="relative inline-flex items-center bg-transparent border-none p-0 cursor-help"
  onmouseenter={() => showTooltip = true}
  onmouseleave={() => showTooltip = false}
  onclick={toggleTooltip}
  type="button"
>
  <div class="calibration-pill">
    <span class="warning-icon">⚠</span>
    <span class="label">Calibrating</span>
  </div>

  {#if showTooltip}
    <div class="tooltip">
      ASTRAPE's physiological models require 42 days of continuous data to fully establish your cardiovascular baseline. Long-term fitness and form scores are currently estimates.
    </div>
  {/if}
</button>

<style>
  .calibration-pill {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    padding: 2px 8px;
    background: var(--glass2);
    border: 1px solid var(--border);
    border-radius: 99px;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    cursor: help;
    transition: all 0.2s ease;
  }

  .calibration-pill:hover {
    background: rgba(255, 255, 255, 0.12);
    border-color: var(--amber);
  }

  .warning-icon {
    color: var(--amber);
    font-size: 10px;
  }

  .label {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 9px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text1);
  }

  .tooltip {
    position: absolute;
    bottom: calc(100% + 8px);
    left: 50%;
    transform: translateX(-50%);
    width: 200px;
    padding: 10px 12px;
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 12px;
    color: var(--text0);
    font-size: 11px;
    line-height: 1.4;
    font-family: 'Space Grotesk', sans-serif;
    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.4);
    z-index: 50;
    pointer-events: none;
    animation: fadeIn 0.15s ease-out;
  }

  @keyframes fadeIn {
    from { opacity: 0; transform: translateX(-50%) translateY(4px); }
    to { opacity: 1; transform: translateX(-50%) translateY(0); }
  }

  /* Space Mono for numbers if needed, though not used in this specific badge text */
</style>
