<script lang="ts" module>
  export type UiIconName =
    | 'link'
    | 'moon'
    | 'bike'
    | 'gauge'
    | 'calendar-plus'
    | 'chat'
    | 'pulse'
    | 'mail'
    | 'check'
    | 'chevron-left'
    | 'chevron-right'
    | 'refresh'
    | 'plus'
    | 'arrow-up';
</script>

<script lang="ts">
  /** Line icons in the same 24px / 1.6 stroke style as BottomNav. */
  let {
    name,
    size = 20,
    strokeWidth = 1.6,
    class: className = '',
  }: { name: UiIconName; size?: number; strokeWidth?: number; class?: string } = $props();
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width={strokeWidth}
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
  class={className}
>
  {#if name === 'link'}
    <path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7" />
    <path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7" />
  {:else if name === 'moon'}
    <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z" />
  {:else if name === 'bike'}
    <circle cx="5.5" cy="17" r="3.5" />
    <circle cx="18.5" cy="17" r="3.5" />
    <path d="M15 6h2l1.5 11M5.5 17 9 9h7l-4 8M9 9 8 6.5H6" />
  {:else if name === 'gauge'}
    <path d="M4.5 18a9 9 0 1 1 15 0" />
    <path d="m12 14 4-5" />
    <circle cx="12" cy="14" r="1" fill="currentColor" />
  {:else if name === 'calendar-plus'}
    <rect x="3" y="5" width="18" height="16" rx="3" />
    <path d="M3 10h18M8 3v4M16 3v4M12 13v5M9.5 15.5h5" />
  {:else if name === 'chat'}
    <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" />
  {:else if name === 'pulse'}
    <path d="M3 12h4l3-7 4 14 3-7h4" />
  {:else if name === 'mail'}
    <rect x="3" y="5" width="18" height="14" rx="3" />
    <path d="m4 7 8 6 8-6" />
  {:else if name === 'check'}
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  {:else if name === 'chevron-left'}
    <path d="m15 5-7 7 7 7" />
  {:else if name === 'chevron-right'}
    <path d="m9 5 7 7-7 7" />
  {:else if name === 'refresh'}
    <path d="M20 11a8 8 0 0 0-14.5-4.5L4 8M4 4v4h4" />
    <path d="M4 13a8 8 0 0 0 14.5 4.5L20 16M20 20v-4h-4" />
  {:else if name === 'plus'}
    <path d="M12 5v14M5 12h14" />
  {:else if name === 'arrow-up'}
    <path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" />
  {/if}
</svg>
