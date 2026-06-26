<script lang="ts">
  import { App } from '@capacitor/app';
  import { Browser } from '@capacitor/browser';
  import { Capacitor } from '@capacitor/core';
  import Icon from '@iconify/svelte';
  import Card from '$lib/components/Card.svelte';
  import Modal from '$lib/components/Modal.svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { HealthIntegration } from '$lib/integrations/health';
  import { api } from '$lib/api';
  import { getAuthHeaders } from '$lib/apiAuth';

  const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

  let syncing = $state('');
  let showIntervalsModal = $state(false);
  let intervalsAthleteId = $state('');
  let intervalsApiKey = $state('');
  let intervalsError = $state('');
  const intervalsFormReady = $derived(intervalsAthleteId.trim().length > 0 && intervalsApiKey.trim().length > 0);

  const integrations = $derived({
    apple: athleteStore.syncStatus?.integrations?.healthkit || { connected: false },
    garmin: athleteStore.syncStatus?.integrations?.garmin || { connected: false },
    whoop: athleteStore.syncStatus?.integrations?.whoop || { connected: false },
    strava: athleteStore.syncStatus?.integrations?.strava || { connected: false },
    intervals_icu: athleteStore.syncStatus?.integrations?.intervals_icu || { connected: false }
  });

  function goBack() {
    goto('/profile');
  }

  function isOAuthConnectedDeepLink(url: string): boolean {
    try {
      const u = new URL(url);
      if (u.host !== 'connected') return false;
      const p = u.searchParams.get('provider');
      const s = u.searchParams.get('status');
      return (p === 'strava' || p === 'whoop') && s === 'success';
    } catch {
      return false;
    }
  }

  async function refreshSyncAfterOAuth() {
    const syncData = await api.getSyncStatus();
    if (syncData) athleteStore.syncStatus = syncData;
  }

  async function onAppUrlOpen(event: { url: string }) {
    if (!isOAuthConnectedDeepLink(event.url)) return;
    await refreshSyncAfterOAuth();
  }

  $effect(() => {
    const sub = App.addListener('appUrlOpen', onAppUrlOpen);
    return () => {
      void sub.then((h) => h.remove());
    };
  });

  $effect(() => {
    const provider = $page.url.searchParams.get('provider');
    const status = $page.url.searchParams.get('status');
    if (provider && status === 'success') {
      void refreshSyncAfterOAuth();
      void goto('/profile/connections', { replaceState: true });
    }
  });

  async function openOAuthAuthorize(providerPath: 'whoop' | 'strava') {
    const isNative = Capacitor.isNativePlatform();
    const params = new URLSearchParams({ json_url: 'true' });
    if (!isNative) {
      params.set('web_return', `${window.location.origin}/profile/connections`);
    }

    const headers = await getAuthHeaders();
    const res = await fetch(
      `${API_URL}/v1/sync/oauth/${providerPath}/authorize?${params}`,
      { headers }
    );
    if (!res.ok) {
      const detail = (await res.json().catch(() => ({}))) as { detail?: string };
      console.error(`OAuth authorize failed (${res.status}):`, detail.detail ?? res.statusText);
      return;
    }
    const { url } = (await res.json()) as { url: string };
    if (!url) return;

    if (isNative) {
      await Browser.open({ url });
    } else {
      window.location.href = url;
    }
  }

  function closeIntervalsModal() {
    if (syncing === 'intervals_icu') return;
    showIntervalsModal = false;
    intervalsError = '';
    intervalsApiKey = '';
  }

  async function submitIntervalsIcu(event: SubmitEvent) {
    event.preventDefault();
    if (!intervalsFormReady || syncing) return;
    syncing = 'intervals_icu';
    intervalsError = '';
    const result = await api.connectIntervalsIcu({
      intervals_athlete_id: intervalsAthleteId.trim(),
      api_key: intervalsApiKey.trim(),
      days: 90
    });
    if (result?.status === 'success') {
      const syncData = await api.getSyncStatus();
      if (syncData) athleteStore.syncStatus = syncData;
      showIntervalsModal = false;
      intervalsApiKey = '';
    } else {
      intervalsError = 'Connection failed';
    }
    syncing = '';
  }

  async function toggleIntegration(id: string) {
    if (syncing) return;
    syncing = id;

    if (id === 'apple') {
      if (integrations.apple.connected) {
        await athleteStore.unlinkIntegration('healthkit');
      } else {
        const granted = await HealthIntegration.requestPermissions();
        if (granted) {
          await HealthIntegration.syncRecentData();
          const syncData = await api.getSyncStatus();
          if (syncData) athleteStore.syncStatus = syncData;
        }
      }
    } else if (id === 'whoop') {
      if (integrations.whoop.connected) {
        await athleteStore.unlinkIntegration('whoop');
      } else {
        await openOAuthAuthorize('whoop');
      }
    } else if (id === 'strava') {
      if (integrations.strava.connected) {
        await athleteStore.unlinkIntegration('strava');
      } else {
        await openOAuthAuthorize('strava');
      }
    } else if (id === 'intervals_icu') {
      if (integrations.intervals_icu.connected) {
        await athleteStore.unlinkIntegration('intervals_icu');
      } else {
        showIntervalsModal = true;
      }
    } else if (id === 'garmin') {
      if (integrations.garmin.connected) {
        await athleteStore.unlinkIntegration('garmin');
      } else {
        await new Promise((resolve) => setTimeout(resolve, 1500));
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
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-3 min-w-0">
            <div
              class="w-9 h-9 rounded-xl flex items-center justify-center border border-border bg-glass shrink-0"
            >
              <!-- Iconify + Simple Icons: https://iconify.design/ -->
              <Icon icon="simple-icons:apple" width={22} height={22} color="#FFFFFF" aria-hidden="true" />
            </div>
            <div class="min-w-0">
              <p class="text-[13px] font-medium">Apple Health</p>
              <p class="text-[10px] text-text2">Sleep & Workouts</p>
              {#if integrations.apple.connected}
                <span
                  class="mt-1 inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wide bg-teal-dim text-teal border border-teal/30"
                >
                  <Icon icon="simple-icons:apple" width={12} height={12} color="#FFFFFF" aria-hidden="true" />
                  Connected
                </span>
              {/if}
            </div>
          </div>
          <span
            class="px-3 py-1 rounded-full text-[10px] font-mono uppercase tracking-wide shrink-0 border border-border bg-glass text-text2"
          >
            Coming soon
          </span>
        </div>

        <!-- Garmin -->
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-3 min-w-0">
            <div
              class="w-9 h-9 rounded-xl flex items-center justify-center border shrink-0"
              style="background: rgba(0, 160, 233, 0.14); border-color: rgba(0, 160, 233, 0.28)"
            >
              <!-- Garmin Connect app blue -->
              <Icon icon="simple-icons:garmin" width={22} height={22} color="#00A0E9" aria-hidden="true" />
            </div>
            <div class="min-w-0">
              <p class="text-[13px] font-medium">Garmin Connect</p>
              <p class="text-[10px] text-text2">Performance Data</p>
              {#if integrations.garmin.connected}
                <span
                  class="mt-1 inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wide bg-teal-dim text-teal border border-teal/30"
                >
                  <Icon icon="simple-icons:garmin" width={12} height={12} color="#00A0E9" aria-hidden="true" />
                  Connected
                </span>
              {/if}
            </div>
          </div>
          <span
            class="px-3 py-1 rounded-full text-[10px] font-mono uppercase tracking-wide shrink-0 border border-border bg-glass text-text2"
          >
            Coming soon
          </span>
        </div>

        <!-- Intervals.icu -->
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-3 min-w-0">
            <div
              class="w-9 h-9 rounded-xl flex items-center justify-center border shrink-0"
              style="background: rgba(221, 4, 71, 0.12); border-color: rgba(221, 4, 71, 0.28)"
            >
              <img src="/intervals-icu-logo.svg" alt="" class="w-[23px] h-[23px]" aria-hidden="true" />
            </div>
            <div class="min-w-0">
              <p class="text-[13px] font-medium">Intervals.icu</p>
              <p class="text-[10px] text-text2">Wearables & training log</p>
              {#if integrations.intervals_icu.connected}
                <span
                  class="mt-1 inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wide bg-teal-dim text-teal border border-teal/30"
                >
                  <img src="/intervals-icu-logo.svg" alt="" class="w-3 h-3" aria-hidden="true" />
                  Connected
                </span>
              {/if}
            </div>
          </div>
          <button
            class="px-3 py-1 rounded-full text-[11px] font-medium cursor-pointer transition-all duration-200 shrink-0 border {integrations.intervals_icu.connected
              ? 'bg-red-dim text-red border-red/30'
              : 'border-[rgba(221,4,71,0.32)] bg-[rgba(221,4,71,0.14)] text-[#DD0447]'}"
            onclick={() => toggleIntegration('intervals_icu')}
          >
            {syncing === 'intervals_icu' ? '...' : integrations.intervals_icu.connected ? 'Unlink' : 'Connect'}
          </button>
        </div>

        <!-- WHOOP -->
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-3 min-w-0">
            <div
              class="w-9 h-9 rounded-xl flex items-center justify-center border shrink-0 bg-bg2"
              style="border-color: rgba(255,255,255,0.12)"
            >
              <Icon icon="arcticons:whoop" width={22} height={22} color="#FFFFFF" aria-hidden="true" />
            </div>
            <div class="min-w-0">
              <p class="text-[13px] font-medium">WHOOP</p>
              <p class="text-[10px] text-text2">Recovery & HRV</p>
              {#if integrations.whoop.connected}
                <span
                  class="mt-1 inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wide bg-teal-dim text-teal border border-teal/30"
                >
                  <Icon icon="arcticons:whoop" width={12} height={12} color="#FFFFFF" aria-hidden="true" />
                  Connected
                </span>
              {/if}
            </div>
          </div>
          <button
            class="px-3 py-1 rounded-full text-[11px] font-medium cursor-pointer transition-all duration-200 shrink-0 border {integrations.whoop.connected
              ? 'bg-red-dim text-red border-red/30'
              : 'bg-amber-dim text-amber border-amber/30'}"
            onclick={() => toggleIntegration('whoop')}
          >
            {syncing === 'whoop' ? '...' : integrations.whoop.connected ? 'Unlink' : 'Connect'}
          </button>
        </div>

        <!-- Strava -->
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-3 min-w-0">
            <div
              class="w-9 h-9 rounded-xl flex items-center justify-center border shrink-0"
              style="background: rgba(252,76,2,0.12); border-color: rgba(252,76,2,0.28)"
            >
              <Icon icon="simple-icons:strava" width={22} height={22} color="#FC4C02" aria-hidden="true" />
            </div>
            <div class="min-w-0">
              <p class="text-[13px] font-medium">Strava</p>
              <p class="text-[10px] text-text2">Activities & routes</p>
              {#if integrations.strava.connected}
                <span
                  class="mt-1 inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono uppercase tracking-wide bg-teal-dim text-teal border border-teal/30"
                >
                  <Icon icon="simple-icons:strava" width={12} height={12} color="#FC4C02" aria-hidden="true" />
                  Connected
                </span>
              {/if}
            </div>
          </div>
          <button
            class="px-3 py-1 rounded-full text-[11px] font-medium cursor-pointer transition-all duration-200 shrink-0 border {integrations.strava.connected
              ? 'bg-red-dim text-red border-red/30'
              : 'border-[rgba(252,76,2,0.3)] bg-[rgba(252,76,2,0.15)] text-[#FC4C02]'}"
            onclick={() => toggleIntegration('strava')}
          >
            {syncing === 'strava' ? '...' : integrations.strava.connected ? 'Unlink' : 'Connect'}
          </button>
        </div>
      </div>
    </Card>
  </div>
</div>

<Modal show={showIntervalsModal} title="Intervals.icu" onClose={closeIntervalsModal}>
  <form class="flex flex-col gap-4" onsubmit={submitIntervalsIcu}>
    <label class="flex flex-col gap-1.5">
      <span class="text-[11px] font-mono uppercase tracking-wide text-text2">Athlete ID</span>
      <input
        class="w-full bg-bg2 border border-border rounded-xl px-3 py-2 text-[14px] outline-none focus:border-teal"
        bind:value={intervalsAthleteId}
        placeholder="i12345"
        autocomplete="off"
      />
    </label>

    <label class="flex flex-col gap-1.5">
      <span class="text-[11px] font-mono uppercase tracking-wide text-text2">API key</span>
      <input
        class="w-full bg-bg2 border border-border rounded-xl px-3 py-2 text-[14px] outline-none focus:border-teal"
        bind:value={intervalsApiKey}
        type="password"
        autocomplete="off"
      />
    </label>

    {#if intervalsError}
      <p class="text-[12px] text-red">{intervalsError}</p>
    {/if}

    <div class="flex gap-2 justify-end pt-1">
      <button
        type="button"
        class="px-4 py-2 rounded-xl border border-border bg-glass text-[13px] text-text1"
        onclick={closeIntervalsModal}
      >
        Cancel
      </button>
      <button
        type="submit"
        disabled={!intervalsFormReady || syncing === 'intervals_icu'}
        class="px-4 py-2 rounded-xl border border-teal/30 bg-teal-dim text-[13px] font-medium text-teal disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {syncing === 'intervals_icu' ? 'Connecting...' : 'Connect'}
      </button>
    </div>
  </form>
</Modal>
