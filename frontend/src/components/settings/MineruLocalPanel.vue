<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import type { MineruLocalConfig, MineruStatus } from '../../types/paper'
import {
  cancelMineruInstall,
  fetchMineruStatus,
  followMineruInstall,
  startMineruInstall,
  stopMineruServer,
  uninstallMineru,
} from '../../services/api'

const props = defineProps<{
  config: MineruLocalConfig
}>()

const status = ref<MineruStatus | null>(null)
const log = ref<string[]>([])
const busy = ref(false)
const error = ref('')
const logRef = ref<HTMLElement | null>(null)
const confirmingUninstall = ref(false)
let stopFollowing: (() => void) | null = null

async function refresh() {
  try {
    status.value = await fetchMineruStatus()
  } catch (e) {
    error.value = (e as Error).message
  }
}

function follow() {
  stopFollowing?.()
  log.value = []
  const { abort } = followMineruInstall({
    onLog: async (line) => {
      log.value.push(line)
      if (log.value.length > 300) log.value.splice(0, log.value.length - 300)
      await nextTick()
      if (logRef.value) logRef.value.scrollTop = logRef.value.scrollHeight
    },
    onDone: (event) => {
      status.value = event.status
      if (event.error) error.value = event.error
    },
    onError: (e) => { error.value = e.message },
  })
  stopFollowing = abort
}

async function install() {
  busy.value = true
  error.value = ''
  try {
    status.value = await startMineruInstall(props.config.tier, props.config.source)
    follow()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function run(action: () => Promise<MineruStatus>) {
  busy.value = true
  error.value = ''
  try {
    status.value = await action()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
    confirmingUninstall.value = false
  }
}

onMounted(async () => {
  await refresh()
  if (status.value?.install.running) follow()
  else if (status.value?.install.log_tail.length) log.value = [...status.value.install.log_tail]
})

onUnmounted(() => stopFollowing?.())
</script>

<template>
  <div class="rounded-lg border border-gray-200 bg-gray-50/60 p-4 space-y-3">
    <div class="flex items-start justify-between gap-4">
      <div class="text-xs text-gray-600 space-y-1">
        <p v-if="!status" class="text-gray-400">读取本地 MinerU 状态…</p>
        <template v-else>
          <p>
            <span class="font-medium text-gray-900">本地 MinerU：</span>
            <span v-if="status.install.running" class="text-amber-700">安装中 · {{ status.install.step }}</span>
            <span v-else-if="status.installed" class="text-emerald-700">
              已安装 {{ status.version }}（tier={{ status.tier }}, {{ status.source }}）
            </span>
            <span v-else class="text-gray-500">未安装</span>
          </p>
          <p v-if="status.installed">
            服务：{{ status.server_running ? `运行中 ${status.server_url}` : '未运行（解析时自动启动，空闲 10 分钟后停止）' }}
          </p>
          <p class="text-gray-400">
            安装 MinerU 并拉取模型检查点约需 3–6 GB 磁盘（可用 {{ status.disk_free_gb }} GB），建议 16 GB 内存。
            <span v-if="!status.uv_available" class="text-red-600">未找到 uv，无法安装。</span>
          </p>
          <p v-if="status.installed && status.tier !== config.tier" class="text-amber-700">
            已安装的模型为 tier={{ status.tier }}，当前选择 {{ config.tier }}：请重新拉取模型。
          </p>
        </template>
      </div>
      <div class="flex flex-col gap-1.5 flex-shrink-0">
        <button
          v-if="status?.install.running"
          :disabled="busy"
          class="px-3 py-1.5 text-xs font-medium text-red-700 bg-white border border-red-200 rounded-lg hover:bg-red-50 disabled:opacity-50"
          @click="run(cancelMineruInstall)"
        >
          取消安装
        </button>
        <button
          v-else
          :disabled="busy || !status?.uv_available"
          class="px-3 py-1.5 text-xs font-medium text-white bg-[var(--color-ink-900)] rounded-lg hover:bg-[var(--color-ink-700)] disabled:opacity-50"
          @click="install"
        >
          {{ status?.installed ? '更新 / 重新拉取模型' : '安装并拉取模型' }}
        </button>
        <button
          v-if="status?.server_running"
          :disabled="busy"
          class="px-3 py-1.5 text-xs font-medium text-gray-700 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50"
          @click="run(stopMineruServer)"
        >
          停止服务
        </button>
        <template v-if="status?.installed && !status.install.running">
          <button
            v-if="!confirmingUninstall"
            :disabled="busy"
            class="px-3 py-1.5 text-xs font-medium text-gray-500 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-50"
            @click="confirmingUninstall = true"
          >
            卸载
          </button>
          <button
            v-else
            :disabled="busy"
            class="px-3 py-1.5 text-xs font-medium text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50"
            @click="run(uninstallMineru)"
          >
            确认删除模型与环境
          </button>
        </template>
      </div>
    </div>

    <pre
      v-if="log.length"
      ref="logRef"
      class="max-h-48 overflow-y-auto bg-[var(--color-ink-900)] text-gray-200 text-[10px] leading-relaxed rounded-md p-2 font-mono whitespace-pre-wrap break-all"
    >{{ log.join('\n') }}</pre>
    <p v-if="error" class="text-xs text-red-600 break-all">{{ error }}</p>
  </div>
</template>
