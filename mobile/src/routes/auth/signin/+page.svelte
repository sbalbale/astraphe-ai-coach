<script lang="ts">
  import { supabase } from '$lib/supabase';
  import { goto } from '$app/navigation';
  
  let email = $state('');
  let password = $state('');
  let loading = $state(false);
  let errorMsg = $state('');

  async function handleSignIn(e: Event) {
    e.preventDefault();
    loading = true;
    errorMsg = '';
    
    const { error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (error) {
      errorMsg = error.message;
      loading = false;
    } else {
      goto('/dashboard');
    }
  }
</script>

<div class="min-h-full flex flex-col p-6 items-center justify-center relative">
  <!-- Decor elements -->
  <div class="absolute top-0 left-0 w-full h-[300px] bg-gradient-to-b from-[rgba(70,33,255,0.15)] to-transparent pointer-events-none"></div>
  <div class="absolute -top-[100px] -right-[100px] w-[300px] h-[300px] bg-teal rounded-full blur-[120px] opacity-20 pointer-events-none"></div>

  <div class="w-full max-w-sm z-10">
    <div class="mb-10 text-center">
      <div class="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue to-teal flex items-center justify-center mx-auto mb-6 shadow-[0_4px_32px_rgba(70,33,255,0.4)]">
        <span class="text-3xl font-bold text-white">A</span>
      </div>
      <h1 class="text-3xl font-bold tracking-tight mb-2">Welcome Back</h1>
      <p class="text-text2 text-sm">Sign in to sync your AI coaching data</p>
    </div>

    {#if errorMsg}
      <div class="p-3 bg-red-dim border-l-2 border-red rounded-lg mb-6 text-xs text-text0 leading-relaxed">
        {errorMsg}
      </div>
    {/if}

    <form onsubmit={handleSignIn} class="flex flex-col gap-4">
      <div>
        <label for="email" class="block text-[10px] text-text2 font-mono uppercase tracking-widest mb-1.5 ml-1">Email</label>
        <input 
          id="email" 
          type="email" 
          bind:value={email} 
          required
          class="w-full px-4 py-3.5 bg-glass border border-border rounded-xl text-text0 text-sm outline-none focus:border-blue focus:bg-glass2 transition-colors placeholder:text-text2"
          placeholder="athlete@example.com"
        />
      </div>
      
      <div>
        <div class="flex justify-between items-baseline ml-1 mb-1.5">
          <label for="password" class="block text-[10px] text-text2 font-mono uppercase tracking-widest">Password</label>
          <button type="button" class="text-[10px] text-teal hover:underline font-mono bg-transparent border-none cursor-pointer">Forgot?</button>
        </div>
        <input 
          id="password" 
          type="password" 
          bind:value={password} 
          required
          class="w-full px-4 py-3.5 bg-glass border border-border rounded-xl text-text0 text-sm outline-none focus:border-blue focus:bg-glass2 transition-colors placeholder:text-text2"
          placeholder="••••••••"
        />
      </div>

      <button 
        type="submit" 
        disabled={loading}
        class="w-full mt-4 py-3.5 bg-blue text-white font-semibold rounded-xl hover:bg-[#3d1ae6] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {loading ? 'Signing In...' : 'Sign In'}
      </button>
    </form>

    <p class="text-center text-xs text-text2 mt-8">
      Don't have an account? <a href="/auth/signup" class="text-white hover:text-teal transition-colors">Sign up</a>
    </p>
  </div>
</div>
