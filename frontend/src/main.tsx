import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

// StrictMode is intentionally removed — it double-mounts components in React 18
// which causes state resets and effect double-fires that break the chat session.
ReactDOM.createRoot(document.getElementById('root')!).render(<App />)
