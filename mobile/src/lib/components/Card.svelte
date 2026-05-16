<script lang="ts">
  import type { Snippet } from 'svelte';
  
  let {
    children,
    style = '',
    glass2 = false,
    paddingClass = 'p-4',
    class: className = '',
  } = $props<{
    children: Snippet;
    style?: string;
    glass2?: boolean;
    /** Overrides default inner padding when you need tighter/aligned metric cards */
    paddingClass?: string;
    class?: string;
  }>();
</script>

<div
  class="rounded-2xl border border-border {glass2 ? 'bg-glass2' : 'bg-glass'} {paddingClass} {className}"
  style={style}
>
  {@render children()}
</div>
