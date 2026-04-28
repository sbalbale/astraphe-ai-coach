<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { goto } from '$app/navigation';
  import { HealthIntegration } from '$lib/integrations/health';

  const menu = [
    { label: 'Personal Information', href: '/profile/personal-info' },
    { label: 'Training Settings', href: '/profile/training-settings' },
    { label: 'Notifications', href: '/profile/notifications' },
    { label: 'Privacy', href: '/profile/privacy' }
  ];

  let syncing = $state('');

  const integrations = $derived({
    apple: athleteStore.syncStatus?.integrations?.healthkit || { connected: false },
    garmin: athleteStore.syncStatus?.integrations?.garmin || { connected: false },
    whoop: athleteStore.syncStatus?.integrations?.whoop || { connected: false }
  });

  async function toggleIntegration(id: string) {
    if (syncing) return;
    syncing = id;

    const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

    if (id === 'apple') {
      if (integrations.apple.connected) {
        await athleteStore.unlinkIntegration('apple');
      } else {
        const granted = await HealthIntegration.requestPermissions();
        if (granted) {
          await HealthIntegration.syncRecentData();
          athleteStore.syncStatus = {
            ...athleteStore.syncStatus,
            integrations: { ...integrations, apple: { connected: true } }
          };
        }
      }
    } else if (id === 'whoop') {
      if (integrations.whoop.connected) {
        await athleteStore.unlinkIntegration('whoop');
      } else {
        window.location.href = `${API_URL}/v1/sync/oauth/whoop/authorize?athlete_id=${athleteStore.profile?.id}`;
      }
    } else if (id === 'garmin') {
      if (integrations.garmin.connected) {
        await athleteStore.unlinkIntegration('garmin');
      } else {
        await new Promise(resolve => setTimeout(resolve, 1500));
        athleteStore.syncStatus = {
          ...athleteStore.syncStatus,
          integrations: { ...integrations, garmin: { connected: true } }
        };
      }
    }
    
    syncing = '';
  }

  async function handleSignOut() {
    await authStore.signOut();
    goto('/auth/signin');
  }
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">Athlete Profile</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Me</h1>
  </div>

  <Card style="background: linear-gradient(135deg, rgba(70,33,255,0.1), rgba(0,200,168,0.05)); text-align: center; padding-top: 24px; padding-bottom: 24px;">
    <div class="w-20 h-20 rounded-full bg-gradient-to-br from-blue to-teal flex items-center justify-center text-[32px] text-white font-bold mx-auto mb-3 shadow-[0_4px_24px_rgba(70,33,255,0.3)]">
      {athleteStore.profile?.display_name?.charAt(0)?.toUpperCase() || authStore.user?.user_metadata?.full_name?.charAt(0)?.toUpperCase() || 'M'}
    </div>
    <h2 class="text-[18px] font-bold mb-1">{athleteStore.profile?.display_name || authStore.user?.user_metadata?.full_name || 'Athlete'}</h2>
    <p class="text-xs text-text2 mb-3">{authStore.user?.email || 'No email provided'}</p>
    <Tag color="var(--teal)">PREMIUM TIER</Tag>
  </Card>

  <Card>
    <p class="text-[13px] font-semibold mb-3">Connected Apps</p>
    <div class="flex flex-col gap-4">
      <!-- Apple Health -->
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="w-9 h-9 rounded-xl bg-[#F07178]/10 text-[#F07178] flex items-center justify-center text-xl border border-[#F07178]/20">🍎</div>
          <div>
            <p class="text-[13px] font-medium">Apple Health</p>
            <p class="text-[10px] text-text2">Sleep & Workouts</p>
          </div>
        </div>
        <button 
          class="px-3 py-1 rounded-full text-[11px] font-medium cursor-pointer transition-all duration-200"
          style={integrations.apple.connected 
            ? 'background: var(--color-red-dim); color: var(--color-red); border: 1px solid rgba(240,113,120,0.3)' 
            : 'background: rgba(240,113,120,0.15); color: #F07178; border: 1px solid rgba(240,113,120,0.3)'}
          onclick={() => toggleIntegration('apple')}
        >
          {syncing === 'apple' ? '...' : integrations.apple.connected ? 'Unlink' : 'Connect'}
        </button>
      </div>

      <!-- Garmin -->
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="w-9 h-9 rounded-xl bg-[#00C8A8]/10 text-[#00C8A8] flex items-center justify-center text-xl border border-[#00C8A8]/20">⌚</div>
          <div>
            <p class="text-[13px] font-medium">Garmin Connect</p>
            <p class="text-[10px] text-text2">Performance Data</p>
          </div>
        </div>
        <button 
          class="px-3 py-1 rounded-full text-[11px] font-medium cursor-pointer transition-all duration-200"
          style={integrations.garmin.connected 
            ? 'background: var(--color-red-dim); color: var(--color-red); border: 1px solid rgba(240,113,120,0.3)' 
            : 'background: rgba(0,200,168,0.15); color: #00C8A8; border: 1px solid rgba(0,200,168,0.3)'}
          onclick={() => toggleIntegration('garmin')}
        >
          {syncing === 'garmin' ? '...' : integrations.garmin.connected ? 'Unlink' : 'Connect'}
        </button>
      </div>

      <!-- WHOOP -->
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="w-9 h-9 rounded-xl bg-[#FFCB88]/10 text-[#FFCB88] flex items-center justify-center text-xl border border-[#FFCB88]/20">🔴</div>
          <div>
            <p class="text-[13px] font-medium">WHOOP</p>
            <p class="text-[10px] text-text2">Recovery & HRV</p>
          </div>
        </div>
        <button 
          class="px-3 py-1 rounded-full text-[11px] font-medium cursor-pointer transition-all duration-200"
          style={integrations.whoop.connected 
            ? 'background: var(--color-red-dim); color: var(--color-red); border: 1px solid rgba(240,113,120,0.3)' 
            : 'background: rgba(255,203,136,0.15); color: #FFCB88; border: 1px solid rgba(255,203,136,0.3)'}
          onclick={() => toggleIntegration('whoop')}
        >
          {syncing === 'whoop' ? '...' : integrations.whoop.connected ? 'Unlink' : 'Connect'}
        </button>
      </div>
    </div>
  </Card>

  <Card>
    <p class="text-[13px] font-semibold mb-3">Account</p>
    <div class="flex flex-col gap-1">
      {#each menu as item}
        <a href={item.href} class="w-full flex justify-between items-center py-2.5 bg-transparent border-none text-text1 text-[13px] cursor-pointer hover:text-text0 transition-colors">
          <span>{item.label}</span>
          <span class="text-text2">→</span>
        </a>
      {/each}
    </div>
  </Card>
  
  <button onclick={handleSignOut} class="w-full p-3 rounded-xl bg-glass border border-border text-[13px] font-medium text-red mt-2 transition-colors hover:bg-red/10 cursor-pointer">
    Sign Out
  </button>
</div>
