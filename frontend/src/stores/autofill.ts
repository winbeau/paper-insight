/**
 * Research-direction auto-fill runs, one per direction (keyed by the direction's client
 * key). Runs are independent: several directions can be filled at once (the backend
 * limits how many agents run concurrently), and a run keeps going when its dialog or
 * the settings modal is closed — the result waits here until it is applied.
 */
import { reactive } from 'vue'
import type { AutofillFields, AutofillResult, AutofillRound, Provider, StreamErrorEvent } from '../types/paper'
import { streamResearchAutofill } from '../services/api'

export type AutofillStatus = 'idle' | 'running' | 'done' | 'error'

export interface AutofillRun {
  status: AutofillStatus
  description: string
  message: string
  thinking: string
  draft: AutofillFields | null
  rounds: AutofillRound[]
  result: AutofillResult | null
  error: StreamErrorEvent | null
  startedAt: number
}

const runs = reactive<Record<string, AutofillRun>>({})
const aborters = new Map<string, () => void>()

function emptyRun(description = ''): AutofillRun {
  return {
    status: 'idle', description, message: '', thinking: '', draft: null,
    rounds: [], result: null, error: null, startedAt: 0,
  }
}

export function useAutofillStore() {
  return {
    runs,

    get(key: string): AutofillRun {
      if (!runs[key]) runs[key] = emptyRun()
      return runs[key]
    },

    start(key: string, description: string, provider?: Provider, model?: string) {
      aborters.get(key)?.()
      const run = emptyRun(description)
      run.status = 'running'
      run.message = '连接推理模型…'
      run.startedAt = Date.now()
      runs[key] = run
      const r = runs[key]  // reactive proxy

      const { abort } = streamResearchAutofill(
        { description, provider, model },
        {
          onStatus: (message) => { r.message = message },
          onThinking: (chunk) => { r.thinking = (r.thinking + chunk).slice(-4000) },
          onDraft: (fields) => { r.draft = fields },
          onRound: (round) => { r.rounds = [...r.rounds, round] },
          onResult: (result) => { r.result = result },
          onError: (error) => {
            r.status = 'error'
            r.error = error
            aborters.delete(key)
          },
          onDone: () => {
            r.status = r.result ? 'done' : 'error'
            if (!r.result && !r.error) r.error = { error: 'unknown', message: '没有得到结果' }
            aborters.delete(key)
          },
        },
      )
      aborters.set(key, abort)
    },

    cancel(key: string) {
      aborters.get(key)?.()
      aborters.delete(key)
      const run = runs[key]
      if (run && run.status === 'running') {
        run.status = 'idle'
        run.message = ''
      }
    },

    /** After the result was applied: keep the description for a re-run, drop the rest. */
    clear(key: string) {
      runs[key] = emptyRun(runs[key]?.description ?? '')
    },
  }
}
