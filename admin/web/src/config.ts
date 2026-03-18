// Admin application configuration

export const config = {
  // App info
  appTitle: import.meta.env.VITE_APP_TITLE || 'AI Skills Admin',

  // API
  apiBaseUrl: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001/api',

  // Portal URL (for cross-linking)
  portalUrl: import.meta.env.VITE_PORTAL_URL || 'http://localhost:5173',

  // Environment
  isDev: import.meta.env.DEV,
  isProd: import.meta.env.PROD,
  mode: import.meta.env.MODE,
}

export default config
