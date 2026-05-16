<script lang="ts">
  import { supabase } from '$lib/supabase';
  import { authRedirectUrl } from '$lib/utils/redirectUrl';

  let email = $state('');
  let loading = $state(false);
  let sent = $state(false);
  let errorMsg = $state('');

  async function handleReset(e: Event) {
    e.preventDefault();
    loading = true;
    errorMsg = '';

    const { error } = await supabase.auth.resetPasswordForEmail(email, {
      redirectTo: authRedirectUrl('reset-password'),
    });

    if (error) {
      errorMsg = error.message;
      loading = false;
    } else {
      sent = true;
      loading = false;
    }
  }
</script>

<div class="min-h-full flex flex-col p-6 items-center justify-center relative">
  <div class="absolute top-0 left-0 w-full h-[300px] bg-gradient-to-b from-[rgba(70,33,255,0.15)] to-transparent pointer-events-none"></div>
  <div class="absolute -top-[100px] -right-[100px] w-[300px] h-[300px] bg-teal rounded-full blur-[120px] opacity-20 pointer-events-none"></div>

  <div class="w-full max-w-sm z-10">
    <button
      type="button"
      onclick={() => history.back()}
      class="w-8 h-8 flex items-center justify-center bg-glass border border-border rounded-lg text-text2 hover:text-text0 transition-colors cursor-pointer mb-8"
      aria-label="Go back"
    >
      ←
    </button>

    {#if sent}
      <div class="text-center">
        <div class="w-16 h-16 rounded-2xl bg-teal/10 border border-teal/20 flex items-center justify-center mx-auto mb-6">
          <span class="text-3xl text-teal">✓</span>
        </div>
        <h1 class="text-3xl font-bold tracking-tight mb-2">Check your email</h1>
        <p class="text-text0 text-sm mb-4 leading-relaxed">
          We sent a reset link to {email}. It expires in 1 hour.
        </p>
        <p class="text-text2 text-xs mb-8">
          Didn't get it? Check your spam folder or go back to try again.
        </p>
        <a
          href="/auth/signin"
          class="block w-full py-3.5 border border-border text-text0 font-semibold rounded-xl text-center text-sm hover:bg-glass transition-colors no-underline"
        >
          Back to Sign In
        </a>
      </div>
    {:else}
      <div class="mb-10">
        <h1 class="text-3xl font-bold tracking-tight mb-2">Forgot Password</h1>
        <p class="text-text2 text-sm">Enter your email and we'll send you a reset link.</p>
      </div>

      {#if errorMsg}
        <div class="p-3 bg-red-dim border-l-2 border-red rounded-lg mb-6 text-xs text-text0 leading-relaxed">
          {errorMsg}
        </div>
      {/if}

      <form onsubmit={handleReset} class="flex flex-col gap-4">
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

        <button
          type="submit"
          disabled={loading}
          class="w-full mt-4 py-3.5 bg-blue text-text0 font-semibold rounded-xl hover:bg-blue/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? 'Sending…' : 'Send Reset Link'}
        </button>
      </form>
    {/if}
  </div>
</div>
