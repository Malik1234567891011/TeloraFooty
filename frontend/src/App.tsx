import { BrowserRouter, Route, Routes } from 'react-router-dom'
import Library from './pages/Library'
import Player from './pages/Player'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Library />} />
        <Route path="/games/:id" element={<Player />} />
      </Routes>
    </BrowserRouter>
  )
}
