import React from 'react'
import ReactDOM from 'react-dom/client'
import { AppProvider } from '@shopify/polaris'
import '@shopify/polaris/build/esm/styles.css'
import App from './App.tsx'
import './index.css'

// Minimal i18n for Polaris
const i18n = {} as any

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AppProvider i18n={i18n}>
      <App />
    </AppProvider>
  </React.StrictMode>,
)

