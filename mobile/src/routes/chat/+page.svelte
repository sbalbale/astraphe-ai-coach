<script lang="ts">
  import { api } from '$lib/api';
  import { athleteStore } from '$lib/stores/athleteStore.svelte';
  import { authStore } from '$lib/stores/authStore.svelte';
  import DOMPurify from 'dompurify';
  import { marked } from 'marked';
  import { tick } from 'svelte';

  type Message = { id: number; role: 'user' | 'ai'; text: string; streaming?: boolean };
  
  const initialText = $derived(`Hey ${authStore.user?.user_metadata?.full_name?.split(' ')[0] || 'there'}! I'm your ASTRAPE Coach. ${athleteStore.ctl > 0 ? `I've analyzed your current fitness (CTL: ${Math.round(athleteStore.ctl)}).` : "Link your data so I can start analyzing your training."} How can I help you today?`);
  
  let messages = $state<Message[]>([{ id: 1, role: 'ai', text: '' }]);
  
  let input = $state('');
  let loading = $state(false);
  let chatContainer: HTMLElement;

  const mdRenderer = new marked.Renderer();
  mdRenderer.link = (...args: any[]) => {
    // Marked's renderer signatures vary by version; support both positional and token-object forms.
    const token = args[0] && typeof args[0] === 'object' ? args[0] : null;
    const href = token?.href ?? args[0];
    const title = token?.title ?? args[1];
    const text = token?.text ?? args[2];

    const safeHref = typeof href === 'string' ? href : '';
    const safeTitle = typeof title === 'string' ? title : undefined;
    const safeText = typeof text === 'string' ? escapeHtmlText(text) : escapeHtmlText(safeHref);
    const titleAttr = safeTitle ? ` title="${escapeHtmlAttr(safeTitle)}"` : '';
    return `<a href="${escapeHtmlAttr(safeHref)}"${titleAttr} target="_blank" rel="noreferrer noopener">${safeText}</a>`;
  };

  marked.setOptions({
    gfm: true,
    breaks: true,
    renderer: mdRenderer
  });

  function escapeHtmlAttr(value: string) {
    return value.replaceAll('&', '&amp;').replaceAll('"', '&quot;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
  }

  function escapeHtmlText(value: string) {
    return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
  }

  function renderAiMarkdown(text: string) {
    // Render markdown → sanitize → render via {@html}.
    const html = marked.parse(text ?? '', { async: false }) as string;
    return DOMPurify.sanitize(html, {
      USE_PROFILES: { html: true },
      ALLOWED_URI_REGEXP: /^(?:(?:https?|mailto|tel):|\/)/i
    });
  }

  $effect(() => {
    // Keep the initial greeting in sync with user/data changes,
    // but only while it is still the very first system message.
    if (messages.length === 0) return;
    const first = messages[0];
    if (first?.id !== 1 || first.role !== 'ai') return;
    if (first.text !== initialText) first.text = initialText;
  });

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
        <img src="/astrape-logo.svg" alt="Astrape" class="w-6 h-6 object-contain" />
      </div>
      <div>
        <p class="font-semibold text-[15px]">ASTRAPE Coach</p>
        <p class="text-[11px] text-teal">● Online · analyzing your data</p>
      </div>
    </div>
  </div>

  <div class="flex-1 overflow-y-auto flex flex-col gap-3 pb-2" bind:this={chatContainer}>
    {#each messages as msg (msg.id)}
      <div class="flex flex-col items-start {msg.role === 'user' ? 'items-end' : ''}">
        {#if msg.role === 'ai'}
          <div class="w-6 h-6 rounded-lg bg-gradient-to-br from-[#4621FF] to-[#00C8A8] flex items-center justify-center mb-1">
            <img src="/astrape-logo.svg" alt="Astrape" class="w-3.5 h-3.5 object-contain" />
          </div>
        {/if}
        <div class="max-w-[82%] px-[14px] py-[10px] text-[13px] leading-[1.55] text-text0 border {msg.role === 'user' ? 'bg-blue rounded-[18px_18px_4px_18px] border-[rgba(70,33,255,0.5)]' : 'bg-glass2 rounded-[4px_18px_18px_18px] border-border'}">
          {#if msg.role === 'ai'}
            {#if msg.streaming && !msg.text.trim()}
              <div class="flex items-center gap-2 text-text1">
                <div class="flex gap-1">
                  <div class="w-1.5 h-1.5 bg-blue rounded-full animate-bounce"></div>
                  <div class="w-1.5 h-1.5 bg-blue rounded-full animate-bounce delay-150"></div>
                  <div class="w-1.5 h-1.5 bg-blue rounded-full animate-bounce delay-300"></div>
                </div>
                <span class="text-[12px]">Thinking…</span>
              </div>
            {:else}
              <div class="chat-md">{@html renderAiMarkdown(msg.text)}</div>
            {/if}
            {#if msg.streaming && msg.text.trim()}
              <span class="animate-[blink_1s_step-end_infinite]">▋</span>
            {/if}
          {:else}
            {msg.text}
          {/if}
        </div>
      </div>
    {/each}
  </div>

  <div class="flex gap-1.5 overflow-x-auto pb-2 shrink-0">
    {#each suggestions as s (s)}
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

<style>
  /* Markdown styles scoped to AI message bubbles */
  :global(.chat-md) {
    word-break: break-word;
  }
  :global(.chat-md :where(p, ul, ol, pre, blockquote)) {
    margin: 0.4rem 0;
  }
  :global(.chat-md :where(ul, ol)) {
    padding-left: 1.1rem;
  }
  :global(.chat-md :where(li)) {
    margin: 0.15rem 0;
  }
  :global(.chat-md :where(a)) {
    color: rgb(0 200 168);
    text-decoration: underline;
    text-underline-offset: 2px;
  }
  :global(.chat-md :where(code)) {
    font-size: 0.92em;
    padding: 0.12rem 0.3rem;
    border-radius: 0.45rem;
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.08);
  }
  :global(.chat-md :where(pre)) {
    overflow-x: auto;
    padding: 0.6rem 0.7rem;
    border-radius: 0.75rem;
    background: rgba(0, 0, 0, 0.25);
    border: 1px solid rgba(255, 255, 255, 0.08);
  }
  :global(.chat-md :where(pre code)) {
    padding: 0;
    border: 0;
    background: transparent;
  }

  @keyframes blink {
    50% {
      opacity: 0;
    }
  }
</style>
