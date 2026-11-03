<script lang="ts">
  import { passwordStrength } from '$lib/utils/passwordStrength';

  /** Four-segment strength bar + label under a new-password field. */
  let { password, minLength, id }: { password: string; minLength: number; id?: string } = $props();

  const strength = $derived(passwordStrength(password, minLength));
  // "Too short" still lights the first segment (red) so the bar never looks idle.
  const filled = $derived(strength.label ? Math.max(1, strength.score) : 0);
  const fill = { none: 'bg-border', red: 'bg-red', amber: 'bg-amber', green: 'bg-green' };
  const text = { none: 'text-text2', red: 'text-red', amber: 'text-amber', green: 'text-green' };
</script>

{#if password}
  <div class="mt-3" {id}>
    <div class="grid grid-cols-4 gap-2" aria-hidden="true">
      {#each [1, 2, 3, 4] as seg (seg)}
        <div class="h-1 rounded-full {filled >= seg ? fill[strength.tone] : 'bg-border'}"></div>
      {/each}
    </div>
    <p class="mt-2 text-[14px] {text[strength.tone]}" aria-live="polite">{strength.label}</p>
  </div>
{/if}
