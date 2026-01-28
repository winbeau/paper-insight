<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{
  show: boolean
  thumbnailUrl: string
  fallbackUrl?: string
  style: { left: string; top: string }
  origin: string
}>()

const currentSrc = ref(props.thumbnailUrl)
const triedFallback = ref(false)

watch(
  () => props.thumbnailUrl,
  (next) => {
    currentSrc.value = next
    triedFallback.value = false
  },
)

function handleError() {
  if (!triedFallback.value && props.fallbackUrl) {
    currentSrc.value = props.fallbackUrl
    triedFallback.value = true
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition
      :enter-active-class="`transition duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] transform ${origin}`"
      enter-from-class="opacity-0 scale-90 translate-y-2 translate-x-[-10px]"
      enter-to-class="opacity-100 scale-100 translate-y-0 translate-x-0"
      :leave-active-class="`transition duration-200 ease-in transform ${origin}`"
      leave-from-class="opacity-100 scale-100 translate-y-0"
      leave-to-class="opacity-0 scale-95 translate-y-2"
    >
      <div
        v-if="show && thumbnailUrl"
        class="fixed z-[9999] pointer-events-none shadow-2xl rounded-lg border-2 border-white bg-white w-[400px] ring-1 ring-black/5 flex flex-col"
        :style="style"
      >
        <div class="w-full relative bg-gray-50 rounded-t-lg overflow-hidden">
          <img
            :src="currentSrc"
            class="w-full h-auto object-contain block"
            alt="Paper Preview"
            @error="handleError"
          />
          <div class="absolute inset-0 bg-gradient-to-t from-black/5 to-transparent pointer-events-none mix-blend-multiply"></div>
        </div>

        <div class="bg-white px-3 py-2 flex items-center justify-between border-t border-gray-100 rounded-b-lg">
          <span class="text-[10px] font-bold text-gray-400 uppercase tracking-wider">First Page Preview</span>
          <span class="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse"></span>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>
