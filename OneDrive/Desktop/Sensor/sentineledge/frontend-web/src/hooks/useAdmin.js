/**
 * src/hooks/useAdmin.js
 *
 * Manages admin password state.
 * Password verified via POST /api/admin/verify-password.
 * Only a boolean marker ('adminVerified') is persisted — the raw password
 * is never stored in sessionStorage.
 */
import { useState, useEffect, useCallback } from 'react'
import { verifyAdminPassword } from '../services/api.js'

export default function useAdmin() {
  const [isAdmin,    setIsAdmin]    = useState(false)
  const [showModal,  setShowModal]  = useState(false)
  const [error,      setError]      = useState('')
  const [loading,    setLoading]    = useState(false)

  // Restore session on mount
  useEffect(() => {
    const verified = sessionStorage.getItem('adminVerified')
    if (verified === '1') setIsAdmin(true)
  }, [])

  const openAdminModal  = useCallback(() => { setError(''); setShowModal(true)  }, [])
  const closeAdminModal = useCallback(() => { setError(''); setShowModal(false) }, [])

  const verifyPassword = useCallback(async (password) => {
    setLoading(true)
    setError('')
    try {
      const data = await verifyAdminPassword(password)
      if (data.valid) {
        sessionStorage.setItem('adminVerified', '1')
        setIsAdmin(true)
        setShowModal(false)
      } else {
        setError('Incorrect password. Please try again.')
      }
    } catch {
      setError('Could not reach server. Check connection.')
    } finally {
      setLoading(false)
    }
  }, [])

  const logout = useCallback(() => {
    sessionStorage.removeItem('adminVerified')
    setIsAdmin(false)
  }, [])

  return { isAdmin, showModal, error, loading, openAdminModal, closeAdminModal, verifyPassword, logout }
}
