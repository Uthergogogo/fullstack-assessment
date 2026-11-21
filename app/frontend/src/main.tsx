import { createRoot } from 'react-dom/client'
import '@fontsource-variable/dm-sans'
import '@fontsource/instrument-serif/latin-400.css'
import { App } from './App'
import './styles.css'

const root = document.getElementById('root')
if (!root) throw new Error('Application root is missing.')
createRoot(root).render(<App />)
