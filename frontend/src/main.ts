import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import { api } from './services/api'

console.log('API Base URL:', api.defaults.baseURL)

createApp(App).mount('#app')
