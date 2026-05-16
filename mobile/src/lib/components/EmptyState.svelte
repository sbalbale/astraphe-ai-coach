<script lang="ts">
  import { goto } from '$app/navigation';
  
  let { title = "No Data Available", message = "Connect a service to sync your metrics.", actionLabel = "Connect App", icon = "🔗" } = $props();
</script>

<div class="flex flex-col items-center justify-center p-6 py-8 text-center bg-glass border border-dashed border-border rounded-2xl">
  <div class="text-3xl mb-3 opacity-80">{icon}</div>
  <h3 class="text-sm font-semibold text-text0 mb-1">{title}</h3>
  <p class="text-[11px] text-text2 max-w-[200px] leading-relaxed mb-4">{message}</p>
  <button 
    onclick={() => goto('/profile')}
    class="px-4 py-1.5 bg-blue text-white text-[11px] font-medium rounded-full hover:bg-blue/80 transition-colors cursor-pointer"
  >
    {actionLabel}
  </button>
</div>
