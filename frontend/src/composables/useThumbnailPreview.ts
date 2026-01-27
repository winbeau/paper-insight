import { ref, type Ref } from 'vue'

export interface ThumbnailPreviewState {
  isHoveringAbstract: Ref<boolean>
  thumbnailStyle: Ref<{ left: string; top: string }>
  previewOrigin: Ref<string>
}

export interface ThumbnailPreviewHandlers {
  handleMouseEnter: (event: MouseEvent) => void
  handleMouseMove: (event: MouseEvent) => void
  handleMouseLeave: () => void
}

export function useThumbnailPreview(
  thumbnailUrl: Ref<string | null>,
  abstractRef: Ref<HTMLElement | null>
): ThumbnailPreviewState & ThumbnailPreviewHandlers {
  const isHoveringAbstract = ref(false)
  const thumbnailStyle = ref({
    left: '0px',
    top: '0px',
  })
  const previewOrigin = ref('origin-left')
  const pendingPreviewStyle = ref<{ left: string; top: string } | null>(null)
  const pendingPreviewOrigin = ref<string | null>(null)
  let reappearTimer: number | null = null

  function calculatePreviewPosition(event: MouseEvent) {
    if (!thumbnailUrl.value) return

    const thumbWidth = 400
    const thumbHeight = 500
    const padding = 16
    const offset = 20
    const viewportWidth = window.innerWidth
    const viewportHeight = window.innerHeight

    let newLeft = event.clientX + offset
    let newTop = event.clientY + offset
    let origin = 'origin-left'

    if (newLeft + thumbWidth + padding > viewportWidth) {
      newLeft = event.clientX - thumbWidth - offset
      origin = 'origin-right'
      if (newLeft < padding) {
        newLeft = padding
      }
    }

    if (newTop + thumbHeight + padding > viewportHeight) {
      newTop = event.clientY - thumbHeight - offset
    }

    newTop = Math.max(padding, Math.min(newTop, viewportHeight - thumbHeight - padding))

    return {
      style: {
        left: `${newLeft}px`,
        top: `${newTop}px`,
      },
      origin,
    }
  }

  function updatePreviewPosition(event: MouseEvent) {
    const result = calculatePreviewPosition(event)
    if (!result) return
    thumbnailStyle.value = result.style
    previewOrigin.value = result.origin
  }

  function handleMouseEnter(event: MouseEvent) {
    if (!abstractRef.value || !thumbnailUrl.value) return
    if (reappearTimer !== null) {
      window.clearTimeout(reappearTimer)
      reappearTimer = null
    }
    updatePreviewPosition(event)
    isHoveringAbstract.value = true
  }

  function handleMouseLeave() {
    if (reappearTimer !== null) {
      window.clearTimeout(reappearTimer)
      reappearTimer = null
    }
    pendingPreviewStyle.value = null
    pendingPreviewOrigin.value = null
    isHoveringAbstract.value = false
  }

  function handleMouseMove(event: MouseEvent) {
    if (!thumbnailUrl.value) return

    const result = calculatePreviewPosition(event)
    if (!result) return

    const nextStyle = result.style
    const origin = result.origin

    if (!isHoveringAbstract.value) {
      pendingPreviewStyle.value = nextStyle
      pendingPreviewOrigin.value = origin
      if (reappearTimer === null) {
        reappearTimer = window.setTimeout(() => {
          if (pendingPreviewStyle.value && pendingPreviewOrigin.value) {
            thumbnailStyle.value = pendingPreviewStyle.value
            previewOrigin.value = pendingPreviewOrigin.value
          }
          pendingPreviewStyle.value = null
          pendingPreviewOrigin.value = null
          isHoveringAbstract.value = true
          reappearTimer = null
        }, 200)
      }
      return
    }

    if (origin !== previewOrigin.value) {
      pendingPreviewStyle.value = nextStyle
      pendingPreviewOrigin.value = origin
      isHoveringAbstract.value = false
      if (reappearTimer === null) {
        reappearTimer = window.setTimeout(() => {
          if (pendingPreviewStyle.value && pendingPreviewOrigin.value) {
            thumbnailStyle.value = pendingPreviewStyle.value
            previewOrigin.value = pendingPreviewOrigin.value
          }
          pendingPreviewStyle.value = null
          pendingPreviewOrigin.value = null
          isHoveringAbstract.value = true
          reappearTimer = null
        }, 200)
      }
      return
    }

    thumbnailStyle.value = nextStyle
    previewOrigin.value = origin
  }

  return {
    isHoveringAbstract,
    thumbnailStyle,
    previewOrigin,
    handleMouseEnter,
    handleMouseMove,
    handleMouseLeave,
  }
}
