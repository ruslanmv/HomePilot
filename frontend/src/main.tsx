import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './ui/App'
import AuthGate from './ui/components/AuthGate'
import './ui/styles.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
<React.StrictMode>
  <AuthGate>
    <App />
  </AuthGate>
</React.StrictMode>
)
