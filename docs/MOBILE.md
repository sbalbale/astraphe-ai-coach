# Mobile

## Svelte 5 + Capacitor Architecture

The APEX mobile app is a Svelte 5 single-page application compiled to a static web bundle and wrapped by Capacitor into a native iOS and Android binary. The WebView executes the compiled JavaScript; Capacitor provides native plugin bridges as typed TypeScript APIs.

---

## Svelte 5 State Management

APEX uses Svelte 5's rune system for all reactive state. There is no external state management library (no Pinia, no Zustand) — runes provide fine-grained reactivity with zero boilerplate.

### Athlete State Store

```typescript
// src/lib/stores/athlete.svelte.ts

import type { AthleteState } from '$lib/api/types';

// Reactive state — accessible anywhere via import
let state = $state<AthleteState | null>(null);
let loading = $state(false);
let lastFetched = $state<Date | null>(null);

export function useAthleteState() {
    async function refresh() {
        loading = true;
        try {
            const response = await api.get<AthleteState>('/athlete/state');
            state = response.data;
            lastFetched = new Date();
        } finally {
            loading = false;
        }
    }
    
    return {
        get state() { return state; },
        get loading() { return loading; },
        get lastFetched() { return lastFetched; },
        refresh,
    };
}
```

### Conversation Store (Coach)

```typescript
// src/lib/stores/conversation.svelte.ts

interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: Date;
    streaming?: boolean;
}

let messages = $state<Message[]>([]);
let conversationId = $state<string | null>(null);

export function useConversation() {
    async function send(text: string) {
        // Optimistic user message
        const userMsg: Message = {
            id: crypto.randomUUID(),
            role: 'user',
            content: text,
            timestamp: new Date(),
        };
        messages = [...messages, userMsg];
        
        // Streaming AI response
        const aiMsg: Message = {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: '',
            timestamp: new Date(),
            streaming: true,
        };
        messages = [...messages, aiMsg];
        
        const stream = await api.stream('/coach/message', {
            conversation_id: conversationId,
            message: text,
        });
        
        for await (const chunk of stream) {
            aiMsg.content += chunk;
            messages = [...messages]; // Trigger reactivity
        }
        
        aiMsg.streaming = false;
        messages = [...messages];
    }
    
    return {
        get messages() { return messages; },
        send,
        clear: () => { messages = []; conversationId = null; },
    };
}
```

---

## API Client

The typed API client wraps all HTTP calls and handles auth token attachment, request retry, and SSE streaming.

```typescript
// src/lib/api/client.ts

import { CapacitorHttp } from '@capacitor/core';
import { getSession } from '$lib/auth';

const BASE_URL = import.meta.env.VITE_API_URL;

async function getHeaders(): Promise<Record<string, string>> {
    const session = await getSession();
    return {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${session.access_token}`,
    };
}

export const api = {
    async get<T>(path: string): Promise<{ data: T }> {
        const response = await CapacitorHttp.get({
            url: `${BASE_URL}${path}`,
            headers: await getHeaders(),
        });
        
        if (response.status >= 400) {
            throw new ApiError(response.data.error);
        }
        
        return { data: response.data };
    },
    
    async post<T>(path: string, body: unknown): Promise<{ data: T }> {
        const response = await CapacitorHttp.post({
            url: `${BASE_URL}${path}`,
            headers: await getHeaders(),
            data: body,
        });
        
        if (response.status >= 400) {
            throw new ApiError(response.data.error);
        }
        
        return { data: response.data };
    },
    
    // SSE streaming for coach responses
    async *stream(path: string, body: unknown): AsyncGenerator<string> {
        const headers = await getHeaders();
        const response = await fetch(`${BASE_URL}${path}`, {
            method: 'POST',
            headers,
            body: JSON.stringify(body),
        });
        
        const reader = response.body!.getReader();
        const decoder = new TextDecoder();
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');
            
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const data = line.slice(6);
                    if (data === '[DONE]') return;
                    yield data;
                }
            }
        }
    },
};
```

---

## HealthKit Integration

HealthKit data is read natively via the Capacitor Background Runner plugin. The background runner executes a JavaScript worker file at scheduled intervals (every hour by default) and whenever the app returns to the foreground.

### Background Runner Script

```javascript
// public/runner.js
// This file runs in a native background context, not in the browser WebView.

addEventListener('healthkitSync', async (resolve, reject, args) => {
    const lastSync = args.lastSyncTimestamp || new Date(Date.now() - 86400000).toISOString();
    
    try {
        // Query HealthKit for new samples
        const workouts = await CapacitorHealthkit.queryWorkouts({
            startDate: lastSync,
            endDate: new Date().toISOString(),
        });
        
        const hrv = await CapacitorHealthkit.queryQuantityType({
            identifier: 'HKQuantityTypeIdentifierHeartRateVariabilitySDNN',
            startDate: lastSync,
            endDate: new Date().toISOString(),
            aggregation: 'daily_min',  // RMSSD lowest = overnight resting HRV
        });
        
        const restingHR = await CapacitorHealthkit.queryQuantityType({
            identifier: 'HKQuantityTypeIdentifierRestingHeartRate',
            startDate: lastSync,
            endDate: new Date().toISOString(),
            aggregation: 'daily_min',
        });
        
        const sleep = await CapacitorHealthkit.querySleepAnalysis({
            startDate: lastSync,
            endDate: new Date().toISOString(),
        });
        
        const spo2 = await CapacitorHealthkit.queryQuantityType({
            identifier: 'HKQuantityTypeIdentifierOxygenSaturation',
            startDate: lastSync,
            endDate: new Date().toISOString(),
            aggregation: 'daily_avg',
        });
        
        // POST batch to APEX API
        const payload = { workouts, hrv, restingHR, sleep, spo2 };
        
        await CapacitorHttp.post({
            url: `${API_BASE_URL}/sync/healthkit/batch`,
            headers: {
                'Content-Type': 'application/json',
                'X-HealthKit-Runner': 'true',
                'Authorization': `Bearer ${args.accessToken}`,
            },
            data: payload,
        });
        
        resolve({ 
            success: true, 
            syncedItems: workouts.length + hrv.length + sleep.length,
            timestamp: new Date().toISOString(),
        });
        
    } catch (error) {
        reject(error.message);
    }
});
```

### Registering the Background Task

```typescript
// src/lib/healthkit.ts

import { BackgroundRunner } from '@capacitor/background-runner';
import { getSession } from '$lib/auth';

export async function registerHealthKitSync() {
    const { access_token } = await getSession();
    
    await BackgroundRunner.dispatchEvent({
        label: 'app.apex-coach.healthkit-sync',
        event: 'healthkitSync',
        details: {
            accessToken: access_token,
            lastSyncTimestamp: localStorage.getItem('lastHealthKitSync'),
        },
    });
}

// Register on app foreground
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
        registerHealthKitSync();
    }
});
```

---

## Supabase Realtime

The mobile client subscribes to Supabase Realtime channels to receive instant updates when new workouts are processed or biometrics are synced. This eliminates the need for polling.

```typescript
// src/lib/realtime.ts

import { createClient } from '@supabase/supabase-js';
import { useAthleteState } from '$lib/stores/athlete.svelte';

const supabase = createClient(
    import.meta.env.VITE_SUPABASE_URL,
    import.meta.env.VITE_SUPABASE_ANON_KEY,
);

export function subscribeToAthleteUpdates(athleteId: string) {
    const { refresh } = useAthleteState();
    
    // Subscribe to tss_history changes (triggers CTL/ATL/TSB update)
    const channel = supabase
        .channel(`athlete-${athleteId}`)
        .on(
            'postgres_changes',
            {
                event: '*',
                schema: 'public',
                table: 'tss_history',
                filter: `athlete_id=eq.${athleteId}`,
            },
            () => refresh(),  // Refetch athlete state on any change
        )
        .on(
            'postgres_changes',
            {
                event: 'INSERT',
                schema: 'public',
                table: 'biometrics',
                filter: `athlete_id=eq.${athleteId}`,
            },
            () => refresh(),
        )
        .subscribe();
    
    return () => supabase.removeChannel(channel);
}
```

---

## Offline Behavior

APEX degrades gracefully without a network connection. The priority is to always show data rather than a blank screen.

| Feature | Offline behavior |
|---|---|
| Dashboard metrics | Shows cached CTL/ATL/TSB from last successful fetch |
| Charts | Renders from locally cached series data |
| Coach chat | Shows message input disabled with "No connection" indicator |
| Workout list | Shows cached workout history |
| Plan | Shows cached plan for the current week |
| Sync | Queues HealthKit payloads locally; flushes when connection restores |

**Local cache strategy:**

```typescript
// src/lib/cache.ts

const CACHE_TTL = {
    athleteState: 5 * 60 * 1000,    // 5 minutes
    workouts: 30 * 60 * 1000,       // 30 minutes
    biometrics: 60 * 60 * 1000,     // 1 hour
    plan: 4 * 60 * 60 * 1000,       // 4 hours
};

export function cache<T>(key: string, ttl: number) {
    return {
        get(): T | null {
            const raw = localStorage.getItem(key);
            if (!raw) return null;
            const { data, timestamp } = JSON.parse(raw);
            if (Date.now() - timestamp > ttl) return null;
            return data as T;
        },
        set(data: T) {
            localStorage.setItem(key, JSON.stringify({
                data,
                timestamp: Date.now(),
            }));
        },
    };
}
```

---

## Capacitor Configuration

```typescript
// capacitor.config.ts

import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
    appId: 'app.apex-coach.ios',
    appName: 'APEX',
    webDir: 'build',
    server: {
        // In development only: point to local dev server
        // Remove for production builds
        url: 'http://192.168.1.xxx:5173',
        cleartext: true,
    },
    plugins: {
        BackgroundRunner: {
            label: 'app.apex-coach.healthkit-sync',
            src: 'runner.js',
            event: 'healthkitSync',
            repeat: true,
            interval: 60,          // minutes between background fetches
            autoStart: true,
        },
        SplashScreen: {
            launchShowDuration: 0,  // APEX handles its own splash
        },
        StatusBar: {
            style: 'dark',          // White icons on dark background
            backgroundColor: '#08080F',
        },
    },
};

export default config;
```
