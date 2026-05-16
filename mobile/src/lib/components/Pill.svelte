<script lang="ts">
  import type { Snippet } from 'svelte';
  
  let { children, active, onclick } = $props<{
    children: Snippet;
    active: boolean;
    onclick: () => void;
  }>();
</script>

<button class="px-[14px] py-[6px] rounded-full text-[12px] font-medium border cursor-pointer transition-all duration-200 font-sans whitespace-nowrap {active ? 'bg-blue text-white border-blue' : 'bg-glass text-text1 border-border'}" onclick={onclick}>
  {@render children()}
</button>
