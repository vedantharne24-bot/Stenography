import { MotionConfig } from 'framer-motion'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles/index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* "user" honours prefers-reduced-motion for every Framer Motion animation. */}
    <MotionConfig reducedMotion="user">
      <App />
    </MotionConfig>
  </StrictMode>,
)
