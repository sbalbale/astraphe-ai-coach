<script lang="ts">
  import { goto } from '$app/navigation';

  let {
    title = "No Data Available",
    message = "Connect a service to sync your metrics.",
    actionLabel = "Connect App",
    icon = "🔗",
    onAction = undefined,
    secondaryLabel = undefined,
    onSecondaryAction = undefined,
  }: {
    title?: string;
    message?: string;
    actionLabel?: string;
    icon?: string;
    onAction?: () => void;
    secondaryLabel?: string;
    onSecondaryAction?: () => void;
  } = $props();
</script>

<div class="flex flex-col items-center justify-center p-6 py-8 text-center bg-glass border border-dashed border-border rounded-2xl">
  <div class="text-3xl mb-3 opacity-80">{icon}</div>
  <h3 class="text-sm font-semibold text-text0 mb-1">{title}</h3>
  <p class="text-[11px] text-text2 max-w-[200px] leading-relaxed mb-4">{message}</p>
  <div class="flex flex-col items-center gap-2">
    <button
      onclick={() => (onAction ? onAction() : goto('/profile'))}
      class="px-4 py-1.5 bg-blue text-white text-[11px] font-medium rounded-full hover:bg-blue/80 transition-colors cursor-pointer"
    >
      {actionLabel}
    </button>
    {#if secondaryLabel && onSecondaryAction}
      <button
        onclick={onSecondaryAction}
        class="px-4 py-1.5 bg-transparent border border-border text-text2 text-[11px] font-medium rounded-full hover:border-blue/50 hover:text-text1 transition-colors cursor-pointer"
      >
        {secondaryLabel}
      </button>
    {/if}
  </div>
</div>
