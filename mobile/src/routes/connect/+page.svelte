<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import { HealthIntegration } from '$lib/integrations/health';
  
  let connected: Record<string, boolean> = $state({ apple: true, garmin: false, whoop: false });
  let syncing = $state('');

  const sources = [
    { id: 'apple', name: 'Apple Health', icon: '🍎', desc: 'Heart rate, sleep, workouts', color: '#F07178' },
    { id: 'garmin', name: 'Garmin Connect', icon: '⌚', desc: 'Training metrics, power', color: '#00C8A8' },
    { id: 'whoop', name: 'WHOOP', icon: '🔴', desc: 'Recovery, strain, sleep stages', color: '#FFCB88' },
  ];

  async function toggle(id: string) {
    if (syncing) return;
    syncing = id;

    if (id === 'apple' && !connected[id]) {
      const granted = await HealthIntegration.requestPermissions();
      if (granted) {
        await HealthIntegration.syncRecentData();
        connected[id] = true;
      } else {
        alert('HealthKit permissions denied.');
      }
    } else {
      // Simulate typical network delay for others
      await new Promise(resolve => setTimeout(resolve, 1500));
      connected[id] = !connected[id];
    }
    
    syncing = '';
  }
</script>

<div class="flex flex-col gap-3 p-4 overflow-y-auto">
  <div class="flex flex-col">
    <p class="text-[12px] text-text2 font-mono uppercase tracking-[0.1em]">Integrations</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Data Sources</h1>
  </div>

  <div class="flex flex-col gap-2.5">
    {#each sources as s}
      <Card style="padding: 14px 16px">
        <div class="flex items-center gap-3">
          <div class="w-11 h-11 rounded-xl shrink-0 flex items-center justify-center text-[22px]" style="background: {s.color}18; border: 1px solid {s.color}40">
            {s.icon}
          </div>
          <div class="flex-1">
            <div class="flex items-center gap-2 mb-0.5">
              <p class="text-[14px] font-semibold">{s.name}</p>
              {#if connected[s.id]}
                <Tag color="var(--color-teal)">LIVE</Tag>
              {/if}
            </div>
            <p class="text-[11px] text-text2">{s.desc}</p>
          </div>
          <button 
            class="px-3.5 py-[7px] rounded-full text-[12px] font-medium cursor-pointer font-sans transition-all duration-200"
            style={connected[s.id] 
              ? 'background: var(--color-red-dim); color: var(--color-red); border: 1px solid rgba(240,113,120,0.3)' 
              : `background: ${s.color}22; color: ${s.color}; border: 1px solid ${s.color}44`}
            onclick={() => toggle(s.id)}
          >
            {syncing === s.id ? '⟳' : connected[s.id] ? 'Unlink' : 'Connect'}
          </button>
        </div>
      </Card>
    {/each}
  </div>
</div>
