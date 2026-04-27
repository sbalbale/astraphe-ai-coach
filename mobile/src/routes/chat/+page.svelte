<script lang="ts">
  import { api } from '$lib/api';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import { tick } from 'svelte';

  type Message = { id: number; role: 'user' | 'ai'; text: string; streaming?: boolean };
  
  let messages = $state<Message[]>([
    { id: 1, role: 'ai', text: `Hey ${authStore.user?.user_metadata?.full_name?.split(' ')[0] || 'there'}! I've reviewed your week. You hit a new CTL high of 68 after Saturday's ride. Your TSB is now +28 — optimal window for a quality effort Tuesday. Ready to plan?` },
  ]);
  
  let input = $state('');
  let loading = $state(false);
  let chatContainer: HTMLElement;

  async function scrollToBottom() {
    await tick();
    if (chatContainer) {
      chatContainer.scrollTop = chatContainer.scrollHeight;
    }
  }

  async function send() {
    const text = input.trim();
    if (!text) return;
    
    input = '';
    const userMsg: Message = { id: Date.now(), role: 'user', text };
    messages.push(userMsg);
    loading = true;
    scrollToBottom();

    const aiMsgId = Date.now() + 1;
    messages.push({ id: aiMsgId, role: 'ai', text: '', streaming: true });
    
    try {
      const stream = api.streamChat(text, athleteStore.recent_tss);
      for await (const chunk of stream) {
        const msgIndex = messages.findIndex(m => m.id === aiMsgId);
        if (msgIndex !== -1) {
          messages[msgIndex].text += chunk;
        }
        scrollToBottom();
      }
    } catch (e) {
      const msgIndex = messages.findIndex(m => m.id === aiMsgId);
      if (msgIndex !== -1) {
        messages[msgIndex].text = "Sorry, I had trouble connecting to the coaching engine.";
      }
    } finally {
      const msgIndex = messages.findIndex(m => m.id === aiMsgId);
      if (msgIndex !== -1) {
        messages[msgIndex].streaming = false;
      }
      loading = false;
    }
  }

  const suggestions = ['Plan this week', 'Am I overtrained?', 'Race day strategy', 'Improve VO2max'];
</script>

<div class="flex flex-col h-full p-4 box-border">
  <div class="pb-3 shrink-0">
    <div class="flex items-center gap-3">
      <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-[#4621FF] to-[#00C8A8] flex items-center justify-center shrink-0">
        <img src="/astrape-logo.svg" alt="Astrape" class="w-6 h-6 object-contain filter invert" />
      </div>
      <div>
        <p class="font-semibold text-[15px]">ASTRAPE Coach</p>
        <p class="text-[11px] text-teal">● Online · analyzing your data</p>
      </div>
    </div>
  </div>

  <div class="flex-1 overflow-y-auto flex flex-col gap-3 pb-2" bind:this={chatContainer}>
    {#each messages as msg}
      <div class="flex flex-col items-start {msg.role === 'user' ? 'items-end' : ''}">
        {#if msg.role === 'ai'}
          <div class="w-6 h-6 rounded-lg bg-gradient-to-br from-[#4621FF] to-[#00C8A8] flex items-center justify-center mb-1">
            <img src="/astrape-logo.svg" alt="Astrape" class="w-3.5 h-3.5 object-contain filter invert" />
          </div>
        {/if}
        <div class="max-w-[82%] px-[14px] py-[10px] text-[13px] leading-[1.55] text-text0 border {msg.role === 'user' ? 'bg-blue rounded-[18px_18px_4px_18px] border-[rgba(70,33,255,0.5)]' : 'bg-glass2 rounded-[4px_18px_18px_18px] border-border'}">
          {msg.text}
          {#if msg.streaming}
            <span class="animate-[blink_1s_step-end_infinite]">▋</span>
          {/if}
        </div>
      </div>
    {/each}
    {#if loading && messages[messages.length - 1].role !== 'ai'}
       <div class="flex flex-col items-start">
         <div class="w-6 h-6 rounded-lg bg-gradient-to-br from-[#4621FF] to-[#00C8A8] flex items-center justify-center mb-1">
           <img src="/astrape-logo.svg" alt="Astrape" class="w-3.5 h-3.5 object-contain filter invert" />
         </div>
         <div class="max-w-[82%] px-[14px] py-[10px] text-[13px] leading-[1.55] text-text0 border bg-glass2 rounded-[4px_18px_18px_18px] border-border flex gap-1">
           <div class="w-1.5 h-1.5 bg-blue rounded-full animate-bounce"></div>
           <div class="w-1.5 h-1.5 bg-blue rounded-full animate-bounce delay-150"></div>
           <div class="w-1.5 h-1.5 bg-blue rounded-full animate-bounce delay-300"></div>
         </div>
       </div>
    {/if}
  </div>

  <div class="flex gap-1.5 overflow-x-auto pb-2 shrink-0">
    {#each suggestions as s}
      <button class="whitespace-nowrap px-3 py-1 rounded-full text-[11px] bg-glass border border-border text-text1 cursor-pointer font-sans" onclick={() => { input = s; }}>{s}</button>
    {/each}
  </div>

  <div class="flex gap-2 shrink-0">
    <input 
      bind:value={input} 
      onkeydown={(e) => e.key === 'Enter' && !loading && send()} 
      placeholder="Ask your coach..." 
      class="flex-1 px-4 py-[11px] rounded-xl text-[13px] bg-glass2 border border-border text-text0 font-sans outline-none"
    />
    <button class="w-11 h-11 rounded-xl shrink-0 text-white text-[18px] flex items-center justify-center transition-all duration-200 border border-border {input.trim() ? 'bg-blue border-blue' : 'bg-glass'}" disabled={loading || !input.trim()} onclick={send}>↑</button>
  </div>
</div>
