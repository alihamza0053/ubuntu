import axios from 'axios'

// Single axios instance for all API calls.
// Token comes from localStorage; 401 responses force re-login.
const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('serverhub_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401 && window.location.pathname !== '/login') {
      localStorage.removeItem('serverhub_token')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  },
)

/** Extract a human-readable message from an axios error. */
export function errorMessage(error) {
  return error.response?.data?.detail || error.message || 'Something went wrong'
}

/**
 * True when a request failed because it was deliberately aborted (an
 * AbortController signal), rather than because something went wrong.
 * Callers use this to stay quiet instead of showing an error.
 */
export function isCancel(error) {
  return axios.isCancel(error)
    || error?.code === 'ERR_CANCELED'
    || error?.name === 'CanceledError'
}

export default api
