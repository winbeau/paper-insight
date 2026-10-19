import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import { api } from './services/api'

async function start() {
  // Static web demo (GitHub Pages): an in-browser mock replaces the local backend.
  // The branch is compiled out of normal builds.
  if (import.meta.env.VITE_DEMO === 'true') {
    const { installDemo } = await import('./demo/mock')
    await installDemo(api)
  }
  createApp(App).mount('#app')
}

start()
