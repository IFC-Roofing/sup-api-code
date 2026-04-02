<template>
  <!-- Floating Action Button -->
  <button
    v-if="!open"
    @click="open = true"
    class="fixed bottom-6 right-6 w-14 h-14 bg-ifc-accent rounded-full shadow-lg shadow-ifc-accent/25
           flex items-center justify-center text-white text-2xl
           hover:bg-blue-500 transition-all duration-300 hover:scale-110 z-50"
  >
    💬
  </button>

  <!-- Chat Panel -->
  <Transition name="chat">
    <div
      v-if="open"
      class="fixed bottom-0 right-0 sm:bottom-6 sm:right-6
             w-full sm:w-96 h-[85vh] sm:h-[600px] sm:rounded-2xl
             bg-ifc-card border border-ifc-border shadow-2xl
             flex flex-col z-50 overflow-hidden"
    >
      <!-- Header -->
      <div class="flex items-center justify-between px-4 py-3 border-b border-ifc-border bg-ifc-dark/50">
        <div class="flex items-center gap-2">
          <span class="text-lg">🏗️</span>
          <span class="font-semibold text-sm">Chat with Sup</span>
        </div>
        <button @click="open = false" class="text-gray-400 hover:text-white p-1">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Messages -->
      <div ref="messagesEl" class="flex-1 overflow-y-auto p-4 space-y-3">
        <div v-if="messages.length === 0" class="text-center py-12">
          <p class="text-2xl mb-2">🏗️</p>
          <p class="text-gray-400 text-sm">Ask me anything about your projects</p>
        </div>

        <div
          v-for="(msg, i) in messages"
          :key="i"
          :class="[
            'max-w-[85%] p-3 rounded-2xl text-sm leading-relaxed',
            msg.role === 'user'
              ? 'ml-auto bg-ifc-accent text-white rounded-br-md'
              : 'bg-ifc-dark/80 text-gray-200 rounded-bl-md'
          ]"
        >
          <p class="whitespace-pre-wrap">{{ msg.content }}</p>
        </div>

        <div v-if="streaming" class="max-w-[85%] p-3 rounded-2xl bg-ifc-dark/80 rounded-bl-md">
          <p class="text-gray-200 text-sm whitespace-pre-wrap">{{ streamBuffer || '...' }}</p>
        </div>
      </div>

      <!-- Input -->
      <div class="p-3 border-t border-ifc-border">
        <form @submit.prevent="send" class="flex gap-2">
          <input
            v-model="input"
            :disabled="streaming"
            placeholder="Ask Sup..."
            class="flex-1 bg-ifc-dark border border-ifc-border rounded-xl px-4 py-2.5 text-sm
                   text-white placeholder-gray-500 focus:outline-none focus:border-ifc-accent
                   disabled:opacity-50 transition-colors"
          />
          <button
            type="submit"
            :disabled="!input.trim() || streaming"
            class="bg-ifc-accent text-white px-4 py-2.5 rounded-xl text-sm font-medium
                   hover:bg-blue-500 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
          >
            Send
          </button>
        </form>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { ref, nextTick, watch } from 'vue'

const open = ref(false)
const input = ref('')
const messages = ref([])
const streaming = ref(false)
const streamBuffer = ref('')
const messagesEl = ref(null)

function scrollToBottom() {
  nextTick(() => {
    if (messagesEl.value) {
      messagesEl.value.scrollTop = messagesEl.value.scrollHeight
    }
  })
}

watch(messages, scrollToBottom, { deep: true })
watch(streamBuffer, scrollToBottom)

async function send() {
  const text = input.value.trim()
  if (!text || streaming.value) return

  messages.value.push({ role: 'user', content: text })
  input.value = ''
  streaming.value = true
  streamBuffer.value = ''

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      messages.value.push({ role: 'assistant', content: err.detail || 'Something went wrong' })
      streaming.value = false
      return
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const data = line.slice(6)
        if (data === '[DONE]') continue
        try {
          const json = JSON.parse(data)
          const delta = json.choices?.[0]?.delta?.content
          if (delta) streamBuffer.value += delta
        } catch {}
      }
    }

    if (streamBuffer.value) {
      messages.value.push({ role: 'assistant', content: streamBuffer.value })
    }
  } catch (e) {
    messages.value.push({ role: 'assistant', content: 'Connection error. Please try again.' })
  }

  streaming.value = false
  streamBuffer.value = ''
}
</script>

<style scoped>
.chat-enter-active, .chat-leave-active {
  transition: all 0.3s ease;
}
.chat-enter-from, .chat-leave-to {
  opacity: 0;
  transform: translateY(20px) scale(0.95);
}
</style>
