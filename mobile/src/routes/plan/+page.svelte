<script lang="ts">
  import Card from '$lib/components/Card.svelte';
  import Tag from '$lib/components/Tag.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { tssTextClass } from '$lib/scoreColors';

  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  
  // Create an array of schedule items based on the plan object or fallback to mock
  let schedule = $derived.by(() => {
    if (athleteStore.plan?.plan) {
      const p = athleteStore.plan.plan;
      return Object.keys(p).map(k => ({
        dateStr: `Apr ${k}`,
        ...p[k]
      }));
    }
    return [];
  });
</script>

<div class="flex flex-col gap-3">
  <div>
    <p class="text-xs text-text2 font-mono uppercase tracking-[0.1em]">AI Orchestrated</p>
    <h1 class="text-[22px] font-bold tracking-[-0.02em]">Training Plan</h1>
  </div>

  {#if schedule.length > 0}
    <div class="flex flex-col gap-2.5">
      {#each schedule as s (s.dateStr)}
        <Card style="padding: 14px; opacity: {s.status === 'done' ? '0.6' : '1'}; border-color: {s.status === 'today' ? 'rgba(70,33,255,0.4)' : 'var(--border)'}; background: {s.status === 'today' ? 'linear-gradient(135deg, rgba(70,33,255,0.1), transparent)' : 'var(--glass)'}">
          <div class="flex gap-3">
            <div class="w-12 flex flex-col items-center shrink-0">
              <span class="text-[10px] text-text2 font-mono uppercase tracking-[0.05em] mb-1">{s.dateStr.split(' ')[0]}</span>
              <span class="text-[18px] font-bold {s.status === 'today' ? 'text-blue' : 'text-text0'}">{s.dateStr.split(' ')[1]}</span>
            </div>
            
            <div class="w-[1px] bg-border shrink-0 self-stretch"></div>
            
            <div class="flex-1 flex flex-col">
              <div class="flex justify-between items-start mb-1">
                <div class="flex items-center gap-2">
                  <div class="w-5 h-5 rounded-md flex items-center justify-center text-[10px]
                    {s.type === 'Run' ? 'bg-blue-dim text-blue' : 
                     s.type === 'Bike' ? 'bg-teal-dim text-teal' : 
                     s.type === 'Rest' ? 'bg-glass2 text-text2' :
                     'bg-amber-dim text-amber'}">
                    {s.type === 'Run' ? '🏃' : s.type === 'Bike' ? '🚴' : s.type === 'Rest' ? '💤' : '💪'}
                  </div>
                  <span class="text-[14px] font-semibold">{s.title}</span>
                </div>
                {#if s.status === 'done'}
                  <span class="text-[10px] text-teal font-mono">DONE</span>
                {:else if s.status === 'today'}
                  <Tag color="var(--blue)">TODAY</Tag>
                {/if}
              </div>
              
              <div class="flex gap-3 mb-2">
                <span class="text-[11px] text-text1">{s.duration}</span>
                <span class="text-[11px] font-mono {Number.isFinite(Number(s?.tss)) ? tssTextClass(s.tss) : 'text-text2'}">{Number.isFinite(Number(s?.tss)) ? s.tss : '--'} TSS</span>
              </div>
              
              <p class="text-[11px] text-text2 leading-relaxed border-l-2 border-[rgba(255,255,255,0.1)] pl-2">{s.note}</p>
            </div>
          </div>
        </Card>
      {/each}
    </div>
  {:else}
    <EmptyState 
      title="No Active Plan" 
      message="Ask the AI Coach to generate a training plan based on your goals and current fitness."
      actionLabel="Go to Chat"
      icon="📋"
    />
  {/if}
</div>
