<script lang="ts">
  import { navTo } from '$lib/nav';
  import { NAV_TABS, activeTabFor } from '$lib/navTabs';

  let { currentPath } = $props<{ currentPath: string }>();

  let activeTab = $derived(activeTabFor(currentPath));
</script>

<div
  class="shrink-0 px-4 pt-2 bg-bg0"
  style="padding-bottom: max(12px, env(safe-area-inset-bottom, 0px));"
>
  <nav
    aria-label="Primary"
    class="grid grid-cols-5 h-16 rounded-[22px] bg-bg3 border border-border"
  >
    {#each NAV_TABS as tab (tab.id)}
      {@const active = activeTab === tab.id}
      <button
        type="button"
        class="flex flex-col items-center justify-center gap-1 bg-transparent border-none cursor-pointer transition-colors duration-200 text-[11px] font-medium {active
          ? 'text-blue'
          : 'text-text2'}"
        onclick={() => navTo(tab.id)}
        aria-current={active ? 'page' : undefined}
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          {#if tab.id === '/dashboard'}
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
          {:else if tab.id === '/training'}
            <path d="M3 12h4l3-7 4 14 3-7h4" />
          {:else if tab.id === '/recovery'}
            <path d="M20.8 8.6a5 5 0 0 0-8.8-3.2 5 5 0 0 0-8.8 3.2c0 5.4 8.8 11 8.8 11s8.8-5.6 8.8-11z" />
          {:else if tab.id === '/plan'}
            <rect x="3" y="5" width="18" height="16" rx="3" />
            <path d="M3 10h18M8 3v4M16 3v4" />
          {:else if tab.id === '/chat'}
            <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" />
          {/if}
        </svg>
        {tab.label}
      </button>
    {/each}
  </nav>
</div>
