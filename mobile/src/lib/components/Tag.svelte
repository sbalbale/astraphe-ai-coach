<script lang="ts">
  import type { Snippet } from 'svelte';
  
  let { children, color } = $props<{
    children: Snippet;
    color: string;
  }>();
</script>

<span class="text-[9px] font-mono uppercase tracking-[0.1em] px-[7px] py-[2px] rounded-full border border-transparent" style="background: {color}22; color: {color}; border-color: {color}44">
  {@render children()}
</span>
