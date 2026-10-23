import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Find the empty page element where React will draw the app.
const rootElement = document.getElementById('root')

if (!rootElement) {
  throw new Error('RepBuddy could not start: the root element is missing.')
}

// Start React. StrictMode checks for common mistakes during development.
createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
