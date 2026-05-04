<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import { goto } from '$app/navigation';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { HealthIntegration } from '$lib/integrations/health';
  import { api } from '$lib/api';

  let syncing = $state('');

  const integrations = $derived({
    apple: athleteStore.syncStatus?.integrations?.healthkit || { connected: false },
    garmin: athleteStore.syncStatus?.integrations?.garmin || { connected: false },
    whoop: athleteStore.syncStatus?.integrations?.whoop || { connected: false }
  });

  function goBack() {
    goto('/profile');
  }

  async function toggleIntegration(id: string) {
    if (syncing) return;
    syncing = id;

    const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

    if (id === 'apple') {
      if (integrations.apple.connected) {
        await athleteStore.unlinkIntegration('healthkit');
      } else {
        const granted = await HealthIntegration.requestPermissions();
        if (granted) {
          await HealthIntegration.syncRecentData();
          // Refresh from backend so UI reflects the real connection state.
          const syncData = await api.getSyncStatus();
          if (syncData) athleteStore.syncStatus = syncData;
        }
      }
    } else if (id === 'whoop') {
      if (integrations.whoop.connected) {
        await athleteStore.unlinkIntegration('whoop');
      } else {
        const aid = athleteStore.profile?.id || '';
        window.location.href = `${API_URL}/v1/sync/oauth/whoop/authorize?athlete_id=${aid}`;
      }
    } else if (id === 'garmin') {
      if (integrations.garmin.connected) {
        await athleteStore.unlinkIntegration('garmin');
      } else {
        await new Promise(resolve => setTimeout(resolve, 1500));
        const syncData = await api.getSyncStatus();
        if (syncData) athleteStore.syncStatus = syncData;
      }
    }

    syncing = '';
  }
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
      <h1 class="text-[22px] font-bold tracking-[-0.02em]">Connected Apps</h1>
    </div>
  </div>

  <div class="flex flex-col gap-3 mt-2">
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
  </div>
</div>
