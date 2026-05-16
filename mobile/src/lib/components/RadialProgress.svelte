<script lang="ts">
  let { value, max = 100, size = 56, color = '#4621FF', label, sub } = $props<{
    value: number;
    max?: number;
    size?: number;
    color?: string;
    label?: string | number;
    sub?: string;
  }>();

  const radius = $derived(size / 2 - 5);
  const circumference = $derived(2 * Math.PI * radius);
  const strokeDashoffset = $derived(circumference - (value / max) * circumference);
  const id = $derived(Math.random().toString(36).substring(2, 9));
</script>

<div class="radial-container" style="width: {size}px; height: {size}px;">
  <svg width={size} height={size}>
    <defs>
      <linearGradient id="grad-{id}" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color={color} />
        <stop offset="100%" stop-color="{color}AA" />
      </linearGradient>
    </defs>
    <!-- Background track -->
    <circle
      cx={size / 2}
      cy={size / 2}
      r={radius}
      fill="transparent"
      stroke="rgba(255,255,255,0.07)"
      stroke-width="4"
    />
    <!-- Progress track -->
    <circle
      cx={size / 2}
      cy={size / 2}
      r={radius}
      fill="transparent"
      stroke="url(#grad-{id})"
      stroke-width="4"
      stroke-linecap="round"
      stroke-dasharray={circumference}
      stroke-dashoffset={strokeDashoffset}
      transform="rotate(-90 {size / 2} {size / 2})"
    />
  </svg>
  <div class="content">
    <span class="label" style="font-size: {size > 50 ? '14px' : '11px'};">{label || value}</span>
    {#if sub}
      <span class="sub">{sub}</span>
    {/if}
  </div>
</div>

<style>
  .radial-container {
    position: relative;
    flex-shrink: 0;
  }
  .content {
    position: absolute;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
  }
  .label {
    font-weight: 700;
    color: #F0F0FF;
    line-height: 1;
  }
  .sub {
    font-size: 8px;
    color: var(--text2);
    font-family: var(--mono);
  }
</style>
