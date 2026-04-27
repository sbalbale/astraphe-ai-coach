<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { goto } from '$app/navigation';

  const menu = [
    { label: 'Personal Information', href: '/profile/personal-info' },
    { label: 'Training Settings', href: '/profile/training-settings' },
    { label: 'Notifications', href: '/profile/notifications' },
    { label: 'Privacy', href: '/profile/privacy' }
  ];

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
      {authStore.user?.user_metadata?.full_name?.charAt(0)?.toUpperCase() || 'M'}
    </div>
    <h2 class="text-[18px] font-bold mb-1">{authStore.user?.user_metadata?.full_name || 'Athlete'}</h2>
    <p class="text-xs text-text2 mb-3">{authStore.user?.email || 'No email provided'}</p>
    <Tag color="var(--teal)">PREMIUM TIER</Tag>
  </Card>

  <Card>
    <p class="text-[13px] font-semibold mb-3">Connected Devices</p>
    <div class="flex flex-col gap-3">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded-full bg-[#FC5200]/20 text-[#FC5200] flex items-center justify-center font-bold text-xs">S</div>
          <div>
            <p class="text-[13px] font-medium">Strava</p>
            <p class="text-[10px] text-text2">Activities</p>
          </div>
        </div>
        <span class="text-[10px] text-teal font-mono">SYNCED 2M AGO</span>
      </div>
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded-full bg-[#00A9E0]/20 text-[#00A9E0] flex items-center justify-center font-bold text-xs">G</div>
          <div>
            <p class="text-[13px] font-medium">Garmin Connect</p>
            <p class="text-[10px] text-text2">Health & Sleep</p>
          </div>
        </div>
        <span class="text-[10px] text-teal font-mono">SYNCED 1H AGO</span>
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
