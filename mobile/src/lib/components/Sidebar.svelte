<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { resolve } from '$app/paths';
  import { navTo } from '$lib/nav';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';

  let { currentPath } = $props<{ currentPath: string }>();

  function onNavClick(e: MouseEvent, path: string) {
    if (
      path === '/training' &&
      $page.url.pathname === '/training' &&
      $page.url.searchParams.has('workout_id')
    ) {
      e.preventDefault();
      goto(resolve('/training'), { keepFocus: true, noScroll: true });
    }
  }

  const ALL_NAV = [
    { id: '/dashboard', label: 'Home' },
    { id: '/training', label: 'Training' },
    { id: '/plan', label: 'Plan' },
    { id: '/zones', label: 'Zones' },
    { id: '/recovery', label: 'Recovery' },
    { id: '/sleep', label: 'Sleep' },
    { id: '/strain', label: 'Strain' },
    { id: '/chat', label: 'Coach' },
    { id: '/profile', label: 'Profile' },
  ];

  const GROUPS = [
    { group: 'Overview', items: ['/dashboard','/training','/plan','/zones'] },
    { group: 'Body', items: ['/recovery','/sleep','/strain'] },
    { group: 'Tools', items: ['/chat','/profile'] },
  ];

  function getIcon(id: string, active: boolean) {
    const c = active ? '#4621FF' : 'currentColor';
    const fill = active ? '#4621FF' : 'none';
    const fillLight = active ? 'rgba(70,33,255,0.2)' : 'none';
    
    switch(id) {
      case '/dashboard':
        return `<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><rect x="3" y="3" width="8" height="8" rx="2" fill="${fill}" stroke="${c}" stroke-width="1.5"/><rect x="13" y="3" width="8" height="8" rx="2" fill="${fill}" stroke="${c}" stroke-width="1.5"/><rect x="3" y="13" width="8" height="8" rx="2" fill="${fill}" stroke="${c}" stroke-width="1.5"/><rect x="13" y="13" width="8" height="8" rx="2" fill="none" stroke="${c}" stroke-width="1.5"/></svg>`;
      case '/training':
        return `<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><polyline points="2,18 8,10 13,14 18,7 22,11" stroke="${c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
      case '/plan':
        return `<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="18" rx="2" stroke="${c}" fill="${fillLight}" stroke-width="1.5"/><line x1="3" y1="9" x2="21" y2="9" stroke="${c}" stroke-width="1.5"/><line x1="8" y1="2" x2="8" y2="6" stroke="${c}" stroke-width="1.5" stroke-linecap="round"/><line x1="16" y1="2" x2="16" y2="6" stroke="${c}" stroke-width="1.5" stroke-linecap="round"/><line x1="7" y1="14" x2="10" y2="14" stroke="${c}" stroke-width="1.5" stroke-linecap="round"/><line x1="7" y1="18" x2="13" y2="18" stroke="${c}" stroke-width="1.5" stroke-linecap="round"/></svg>`;
      case '/zones':
        return `<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" stroke="${c}" stroke-width="1.5"/><circle cx="12" cy="12" r="5" stroke="${c}" stroke-width="1.5" stroke-dasharray="3 2"/><circle cx="12" cy="12" r="2" fill="${fill}"/></svg>`;
      case '/recovery':
        return `<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><path d="M22 12h-4l-3 9L9 3l-3 9H2" stroke="${c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
      case '/sleep':
        return `<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" stroke="${c}" fill="${fillLight}" stroke-width="1.5"/></svg>`;
      case '/strain':
        return `<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" stroke="${c}" fill="${fillLight}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
      case '/chat':
        return `<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" stroke="${c}" fill="${fillLight}" stroke-width="1.5"/></svg>`;

      case '/profile':
        return `<svg width="22" height="22" fill="none" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4" stroke="${c}" fill="${fillLight}" stroke-width="1.5"/><path d="M4 20c0-4 3.6-7 8-7s8 3 8 7" stroke="${c}" stroke-width="1.5" stroke-linecap="round"/></svg>`;
      default:
        return '';
    }
  }
</script>

<div class="w-[220px] bg-bg1 border-r border-border flex flex-col p-6 px-4 gap-1 shrink-0">
  <div class="mb-6 pl-2">
    <p class="font-mono font-bold text-[15px] tracking-[0.1em] text-blue">ASTRAPHE</p>
    <p class="text-[10px] text-text2 font-mono tracking-[0.08em]">AI COACH · v2.1</p>
  </div>
  
  {#each GROUPS as { group, items }}
    <div class="mb-2">
      <p class="text-[9px] text-text2 font-mono uppercase tracking-[0.12em] px-3 pt-1.5 pb-1">{group}</p>
      {#each ALL_NAV.filter(n => items.includes(n.id)) as item}
        {@const active = currentPath === item.id || (currentPath === '/' && item.id === '/dashboard')}
        <button
          type="button"
          class="flex items-center gap-2.5 py-2.25 px-3 rounded-xl w-full font-sans text-[13px] text-left transition-all duration-150 border
          {active ? 'bg-blue-dim border-[rgba(70,33,255,0.25)] text-blue font-semibold' : 'bg-transparent border-transparent text-text1 font-normal'}"
          onclick={(e) => {
            onNavClick(e, item.id);
            if (!e.defaultPrevented) navTo(item.id);
          }}
        >
          <!-- eslint-disable-next-line svelte/no-at-html-tags -->
          {@html getIcon(item.id, active)}
          {item.label}
        </button>
      {/each}
    </div>
  {/each}
  
  <button
    type="button"
    class="mt-auto p-3 bg-glass rounded-xl border border-border cursor-pointer flex items-center gap-2.5 w-full text-left"
    onclick={() => navTo('/profile')}
  >
    <div class="w-8 h-8 rounded-full bg-gradient-to-br from-blue to-teal flex items-center justify-center text-sm shrink-0 text-white font-bold">
      {authStore.user?.user_metadata?.full_name?.charAt(0)?.toUpperCase() || 'A'}
    </div>
    <div>
      <p class="text-xs font-semibold text-text0">{authStore.user?.user_metadata?.full_name || 'Athlete'}</p>
      <p class="text-[10px] text-text2">CTL {Math.round(athleteStore.ctl)} · TSB {athleteStore.tsb > 0 ? '+' : ''}{Math.round(athleteStore.tsb)}</p>
    </div>
  </button>
</div>
