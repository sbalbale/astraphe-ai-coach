<script lang="ts">
  import { navTo } from '$lib/nav';

  let { currentPath } = $props<{ currentPath: string }>();

  const NAV_ITEMS_MOBILE = [
    { id: '/dashboard', label: 'Home' },
    { id: '/recovery', label: 'Body' },
    { id: '/plan', label: 'Plan' },
    { id: '/chat', label: 'Coach' },
    { id: '/profile', label: 'Me' },
  ];

  function getIcon(id: string, active: boolean) {
    const c = active ? '#4621FF' : 'currentColor';
    const fill = active ? '#4621FF' : 'none';
    const fillLight = active ? 'rgba(70,33,255,0.2)' : 'none';

    switch (id) {
      case '/dashboard':
        return `<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><rect x="3" y="3" width="8" height="8" rx="2" fill="${fill}" stroke="${c}" stroke-width="1.5"/><rect x="13" y="3" width="8" height="8" rx="2" fill="${fill}" stroke="${c}" stroke-width="1.5"/><rect x="3" y="13" width="8" height="8" rx="2" fill="${fill}" stroke="${c}" stroke-width="1.5"/><rect x="13" y="13" width="8" height="8" rx="2" fill="none" stroke="${c}" stroke-width="1.5"/></svg>`;
      case '/recovery':
        return `<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><path d="M22 12h-4l-3 9L9 3l-3 9H2" stroke="${c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
      case '/plan':
        return `<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="18" rx="2" stroke="${c}" fill="${fillLight}" stroke-width="1.5"/><line x1="3" y1="9" x2="21" y2="9" stroke="${c}" stroke-width="1.5"/><line x1="8" y1="2" x2="8" y2="6" stroke="${c}" stroke-width="1.5" stroke-linecap="round"/><line x1="16" y1="2" x2="16" y2="6" stroke="${c}" stroke-width="1.5" stroke-linecap="round"/><line x1="7" y1="14" x2="10" y2="14" stroke="${c}" stroke-width="1.5" stroke-linecap="round"/><line x1="7" y1="18" x2="13" y2="18" stroke="${c}" stroke-width="1.5" stroke-linecap="round"/></svg>`;
      case '/chat':
        return `<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" stroke="${c}" fill="${fillLight}" stroke-width="1.5"/></svg>`;
      case '/profile':
        return `<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4" stroke="${c}" fill="${fillLight}" stroke-width="1.5"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" stroke="${c}" stroke-width="1.5" stroke-linecap="round"/></svg>`;
      default:
        return '';
    }
  }
</script>

<div class="flex bg-bg1 border-t border-border pt-2 pb-[max(8px,env(safe-area-inset-bottom))] shrink-0">
  {#each NAV_ITEMS_MOBILE as item}
    {@const active =
      currentPath === item.id || (currentPath === '/' && item.id === '/dashboard')}
    <button
      type="button"
      class="flex-1 flex flex-col items-center gap-1 bg-transparent border-none cursor-pointer py-1 transition-colors duration-200 {active
        ? 'text-blue'
        : 'text-text2'}"
      onclick={() => navTo(item.id)}
      aria-current={active ? 'page' : undefined}
    >
      <!-- eslint-disable-next-line svelte/no-at-html-tags -->
      {@html getIcon(item.id, active)}
      <span class="text-[9px] font-mono tracking-[0.06em] uppercase">{item.label}</span>
    </button>
  {/each}
</div>
