import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './liquid-glass-overrides.css'
import './ios-composer.css'
import './ios-pages.css'
import SkillForge from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <SkillForge />
  </StrictMode>,
)
