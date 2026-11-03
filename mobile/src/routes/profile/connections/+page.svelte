<script lang="ts">
  import { App } from '@capacitor/app';
  import { Browser } from '@capacitor/browser';
  import { Capacitor } from '@capacitor/core';
  import SubpageHeader from '$lib/components/SubpageHeader.svelte';
  import { confirm } from '$lib/confirm';
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


  let showGarminModal = $state(false);
  let garminStep = $state<'credentials' | 'mfa'>('credentials');
  let garminUsername = $state('');
  let garminPassword = $state('');
  let garminMfaCode = $state('');
  let garminStateToken = $state('');
  let garminError = $state('');
  const garminCredentialsReady = $derived(
    garminUsername.trim().length > 0 && garminPassword.trim().length > 0
  );
  const garminMfaReady = $derived(garminMfaCode.trim().length > 0);

  const integrations = $derived({
    apple: athleteStore.syncStatus?.integrations?.healthkit || { connected: false },
    garmin: athleteStore.syncStatus?.integrations?.garmin || { connected: false },
    whoop: athleteStore.syncStatus?.integrations?.whoop || { connected: false },
    strava: athleteStore.syncStatus?.integrations?.strava || { connected: false },
    intervals_icu: athleteStore.syncStatus?.integrations?.intervals_icu || { connected: false }
  });


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
      throw new Error(detail.detail || `Couldn't start the connection (${res.status}).`);
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

  function closeGarminModal() {
    if (syncing === 'garmin') return;
    showGarminModal = false;
    garminStep = 'credentials';
    garminError = '';
    garminPassword = '';
    garminMfaCode = '';
    garminStateToken = '';
  }

  async function refreshAfterConnect() {
    const syncData = await api.getSyncStatus();
    if (syncData) athleteStore.syncStatus = syncData;
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
      await refreshAfterConnect();
      showIntervalsModal = false;
      intervalsApiKey = '';
    } else {
      intervalsError = 'Connection failed';
    }
    syncing = '';
  }

  async function submitGarminCredentials(event: SubmitEvent) {
    event.preventDefault();
    if (!garminCredentialsReady || syncing) return;
    syncing = 'garmin';
    garminError = '';
    const result = await api.connectGarmin({
      username: garminUsername.trim(),
      password: garminPassword,
      days: 90
    });
    if (result?.mfa_required && result?.state_token) {
      garminStateToken = result.state_token;
      garminStep = 'mfa';
      garminPassword = '';
      syncing = '';
      return;
    }
    if (result?.status === 'success') {
      await refreshAfterConnect();
      showGarminModal = false;
      garminStep = 'credentials';
      garminError = '';
      garminUsername = '';
      garminPassword = '';
      garminMfaCode = '';
      garminStateToken = '';
    } else {
      garminError =
        typeof result?.detail === 'string' ? result.detail : 'Connection failed';
    }
    syncing = '';
  }

  async function submitGarminMfa(event: SubmitEvent) {
    event.preventDefault();
    if (!garminMfaReady || syncing || !garminStateToken) return;
    syncing = 'garmin';
    garminError = '';
    const result = await api.connectGarminMfa({
      state_token: garminStateToken,
      mfa_code: garminMfaCode.trim(),
      days: 90
    });
    if (result?.status === 'success') {
      await refreshAfterConnect();
      showGarminModal = false;
      garminStep = 'credentials';
      garminError = '';
      garminUsername = '';
      garminPassword = '';
      garminMfaCode = '';
      garminStateToken = '';
    } else {
      garminError =
        typeof result?.detail === 'string' ? result.detail : 'MFA verification failed';
    }
    syncing = '';
  }

  // Shown above the list. Errors used to only reach the console, and an exception
  // left `syncing` set, disabling every Connect/Unlink button until reload.
  let connectError = $state('');

  async function toggleIntegration(id: string) {
    if (syncing) return;
    syncing = id;
    connectError = '';
    try {
      await runToggle(id);
    } catch (e) {
      connectError = e instanceof Error && e.message ? e.message : 'Something went wrong. Please try again.';
    } finally {
      syncing = '';
    }
  }

  async function runToggle(id: string) {
    if (id === 'apple') {
      if (integrations.apple.connected) {
        await athleteStore.unlinkIntegration('healthkit');
      } else {
        const granted = await HealthIntegration.requestPermissions();
        if (granted) {
          await HealthIntegration.syncRecentData();
          await refreshAfterConnect();
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
        showGarminModal = true;
        garminStep = 'credentials';
        garminError = '';
      }
    }
  }

  type AppId = 'strava' | 'whoop' | 'garmin' | 'apple';
  const APPS: { id: AppId; name: string; mono: string; desc: string }[] = [
    { id: 'strava', name: 'Strava', mono: 'ST', desc: 'Activities & routes' },
    { id: 'whoop', name: 'WHOOP', mono: 'WH', desc: 'Recovery & HRV · sleep' },
    { id: 'garmin', name: 'Garmin Connect', mono: 'GC', desc: 'Wearables & training log' },
    { id: 'apple', name: 'Apple Health', mono: 'AH', desc: 'Sleep & workouts' }
  ];

  const field =
    'w-full h-12 px-3.5 bg-bg0 border border-border rounded-[14px] text-sm text-text0 outline-none focus:border-blue';

  async function unlinkApp(id: string, name: string) {
    const ok = await confirm({
      title: `Unlink ${name}?`,
      message: `Astraphe stops syncing from ${name}. Data already imported stays.`,
      confirmText: 'Unlink',
      cancelText: 'Cancel',
      confirmTone: 'danger'
    });
    if (ok) await toggleIntegration(id);
  }
</script>

<div class="flex flex-col gap-3 pb-6">
  <SubpageHeader
    title="Connected apps"
    subtitle="Where Astraphe reads your training and body data. When two sources overlap, the more accurate sensor wins."
  />
  {#if connectError}
    <p role="alert" class="m-0 px-4 py-3 rounded-[14px] bg-red-dim border border-red/30 text-[13px] text-red">{connectError}</p>
  {/if}

  {#each APPS as app (app.id)}
    {@const connected = integrations[app.id].connected}
    <div class="flex items-center gap-3 p-3.5 rounded-[20px] bg-bg2 border border-border">
      <span aria-hidden="true" class="shrink-0 w-11 h-11 rounded-xl bg-bg3 flex items-center justify-center font-mono text-[13px] text-text1">{app.mono}</span>
      <span class="flex-1 min-w-0 flex flex-col gap-0.5">
        <span class="text-base font-medium">{app.name}</span>
        <span class="text-[13px] text-text2 truncate">{app.desc}</span>
      </span>
      {#if app.id === 'apple'}
        <span class="shrink-0 h-10 px-3 rounded-xl border border-border text-[13px] text-text2 flex items-center">Soon</span>
      {:else if connected}
        <button
          type="button"
          aria-label="Unlink {app.name}"
          class="shrink-0 h-10 px-2 flex items-center gap-1.5 border-0 bg-transparent text-[13px] text-green cursor-pointer disabled:opacity-50"
          disabled={syncing !== ''}
          onclick={() => unlinkApp(app.id, app.name)}
        >
          <span aria-hidden="true" class="w-1.5 h-1.5 rounded-full bg-green"></span>{syncing === app.id ? 'Unlinking…' : 'Connected'}
        </button>
      {:else}
        <button
          type="button"
          class="shrink-0 h-10 px-3.5 rounded-xl border border-border bg-transparent text-blue text-[13px] font-medium cursor-pointer disabled:opacity-50"
          disabled={syncing !== ''}
          onclick={() => toggleIntegration(app.id)}
        >{syncing === app.id ? 'Connecting…' : 'Connect'}</button>
      {/if}
    </div>
  {/each}

  <!-- Intervals.icu: credentials inline -->
  <div class="flex flex-col gap-3 p-4 rounded-[20px] bg-bg2 border {integrations.intervals_icu.connected ? 'border-border' : 'border-blue/25'}">
    <div class="flex items-center gap-3">
      <span aria-hidden="true" class="shrink-0 w-11 h-11 rounded-xl bg-blue-dim flex items-center justify-center font-mono text-[13px] text-blue">IC</span>
      <span class="flex-1 min-w-0 flex flex-col gap-0.5">
        <span class="text-base font-medium">Intervals.icu</span>
        <span class="text-[13px] text-text2 truncate">Workouts & recovery · plan sync</span>
      </span>
      {#if integrations.intervals_icu.connected}
        <button
          type="button"
          aria-label="Unlink Intervals.icu"
          class="shrink-0 h-10 px-2 flex items-center gap-1.5 border-0 bg-transparent text-[13px] text-green cursor-pointer disabled:opacity-50"
          disabled={syncing !== ''}
          onclick={() => unlinkApp('intervals_icu', 'Intervals.icu')}
        >
          <span aria-hidden="true" class="w-1.5 h-1.5 rounded-full bg-green"></span>{syncing === 'intervals_icu' ? 'Unlinking…' : 'Connected'}
        </button>
      {/if}
    </div>
    {#if !integrations.intervals_icu.connected}
      <form class="flex flex-col gap-3" onsubmit={submitIntervalsIcu}>
        <div class="grid grid-cols-2 gap-2.5">
          <label class="flex flex-col gap-1.5">
            <span class="text-xs text-text2">Athlete ID</span>
            <input class={field} bind:value={intervalsAthleteId} placeholder="i12345" autocomplete="off" />
          </label>
          <label class="flex flex-col gap-1.5">
            <span class="text-xs text-text2">API key</span>
            <input class={field} bind:value={intervalsApiKey} type="password" placeholder="••••••••" autocomplete="off" />
          </label>
        </div>
        {#if intervalsError}<p class="m-0 text-xs text-red">{intervalsError}</p>{/if}
        <button
          type="submit"
          disabled={!intervalsFormReady || syncing === 'intervals_icu'}
          class="h-12 rounded-[14px] border-0 bg-blue text-[#0B1420] text-sm font-semibold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
        >{syncing === 'intervals_icu' ? 'Connecting…' : 'Connect Intervals.icu'}</button>
      </form>
    {/if}
  </div>
</div>

<Modal
  show={showGarminModal}
  title={garminStep === 'mfa' ? 'Garmin verification' : 'Garmin Connect'}
  onClose={closeGarminModal}
>
  {#if garminStep === 'credentials'}
    <form class="flex flex-col gap-4" onsubmit={submitGarminCredentials}>
      <p class="m-0 text-[13px] text-text1 leading-relaxed">
        Sign in with your Garmin account. Your password isn't stored — only a session token is kept.
        Changing your Garmin password ends that session.
      </p>
      <label class="flex flex-col gap-1.5">
        <span class="text-xs text-text2">Email or username</span>
        <input class={field} bind:value={garminUsername} autocomplete="username" />
      </label>
      <label class="flex flex-col gap-1.5">
        <span class="text-xs text-text2">Password</span>
        <input class={field} bind:value={garminPassword} type="password" autocomplete="current-password" />
      </label>
      {#if garminError}<p class="m-0 text-xs text-red">{garminError}</p>{/if}
      <div class="flex gap-2">
        <button type="button" class="flex-1 h-12 rounded-[14px] border border-border bg-transparent text-sm text-text0 cursor-pointer" onclick={closeGarminModal}>Cancel</button>
        <button
          type="submit"
          disabled={!garminCredentialsReady || syncing === 'garmin'}
          class="flex-1 h-12 rounded-[14px] border-0 bg-blue text-[#0B1420] text-sm font-semibold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
        >{syncing === 'garmin' ? 'Connecting…' : 'Connect'}</button>
      </div>
    </form>
  {:else}
    <form class="flex flex-col gap-4" onsubmit={submitGarminMfa}>
      <p class="m-0 text-[13px] text-text1 leading-relaxed">Enter the verification code from your Garmin MFA method to finish connecting.</p>
      <label class="flex flex-col gap-1.5">
        <span class="text-xs text-text2">Verification code</span>
        <input class="{field} font-mono" bind:value={garminMfaCode} inputmode="numeric" autocomplete="one-time-code" />
      </label>
      {#if garminError}<p class="m-0 text-xs text-red">{garminError}</p>{/if}
      <div class="flex gap-2">
        <button type="button" class="flex-1 h-12 rounded-[14px] border border-border bg-transparent text-sm text-text0 cursor-pointer" onclick={closeGarminModal}>Cancel</button>
        <button
          type="submit"
          disabled={!garminMfaReady || syncing === 'garmin'}
          class="flex-1 h-12 rounded-[14px] border-0 bg-blue text-[#0B1420] text-sm font-semibold cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
        >{syncing === 'garmin' ? 'Verifying…' : 'Verify'}</button>
      </div>
    </form>
  {/if}
</Modal>
