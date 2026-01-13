import axios from 'axios'

const API_URL = import.meta.env.VITE_API_URL || '[http://localhost:8000](http://localhost:8000)'

// Optional API key stored in localStorage (set in UI if you enable backend API_KEY)
export function getApiKey() {
return localStorage.getItem('homepilot_api_key') || ''
}

export const api = axios.create({
baseURL: API_URL,
timeout: 180000
})

api.interceptors.request.use((config) => {
const k = getApiKey()
if (k) config.headers['X-API-Key'] = k
return config
})
