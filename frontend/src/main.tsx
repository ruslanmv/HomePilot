import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './ui/App'
import AuthGate from './ui/components/AuthGate'
import LegalPage from './ui/components/LegalPage'
import './ui/styles.css'

// Public, pre-auth legal pages. These are reached by full navigation (the login
// footer links, and direct URLs); on the SPA host the server returns index.html
// for any path, so we branch here before mounting the authenticated app.
const path = window.location.pathname.replace(/\/+$/, '') || '/'
const legalKind =
  path === '/terms' ? 'terms' : path === '/privacy' ? 'privacy' : null

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {legalKind ? (
      <LegalPage kind={legalKind} />
    ) : (
      <AuthGate>
        <App />
      </AuthGate>
    )}
  </React.StrictMode>,
)
