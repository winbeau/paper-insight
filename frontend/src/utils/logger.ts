/**
 * Structured logger for PaperInsight frontend.
 *
 * In development mode all levels are printed; in production only
 * warn and error are emitted so that debug/info noise is suppressed.
 */

type LogLevel = 'debug' | 'info' | 'warn' | 'error'

const LEVEL_PRIORITY: Record<LogLevel, number> = {
  debug: 0,
  info: 1,
  warn: 2,
  error: 3,
}

const MIN_LEVEL: LogLevel = import.meta.env.DEV ? 'debug' : 'warn'

function shouldLog(level: LogLevel): boolean {
  return LEVEL_PRIORITY[level] >= LEVEL_PRIORITY[MIN_LEVEL]
}

function formatPrefix(scope: string, level: LogLevel): string {
  const ts = new Date().toISOString().slice(11, 23) // HH:mm:ss.SSS
  return `${ts} | ${level.toUpperCase().padEnd(5)} | ${scope}`
}

export interface Logger {
  debug: (msg: string, ...args: unknown[]) => void
  info: (msg: string, ...args: unknown[]) => void
  warn: (msg: string, ...args: unknown[]) => void
  error: (msg: string, ...args: unknown[]) => void
}

export function getLogger(scope: string): Logger {
  return {
    debug(msg, ...args) {
      if (shouldLog('debug')) console.debug(formatPrefix(scope, 'debug'), '|', msg, ...args)
    },
    info(msg, ...args) {
      if (shouldLog('info')) console.info(formatPrefix(scope, 'info'), '|', msg, ...args)
    },
    warn(msg, ...args) {
      if (shouldLog('warn')) console.warn(formatPrefix(scope, 'warn'), '|', msg, ...args)
    },
    error(msg, ...args) {
      if (shouldLog('error')) console.error(formatPrefix(scope, 'error'), '|', msg, ...args)
    },
  }
}
