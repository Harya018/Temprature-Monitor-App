/**
 * src/pages/SuperAdminLogin.jsx
 *
 * Super Admin portal login — exact same split-card design as LoginPage.jsx.
 * Left panel: dark purple gradient with geometric shapes, "SUPER / ADMIN / PORTAL".
 * Right panel: white form with underline fields.
 *
 * Auth flow:
 *   1. POST /api/admin/login  → {token, username}
 *   2. GET  /api/super-admin/overview (Bearer <token>) → verify super_admin role
 *   3. 200 → save session → /super-admin
 *   4. 403 → "This portal is for super admins only"
 */

import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { User, Lock, Eye, EyeOff, ShieldCheck } from 'lucide-react'

export default function SuperAdminLogin() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error,    setError]    = useState('')
  const [loading,  setLoading]  = useState(false)
  const [shaking,  setShaking]  = useState(false)
  const [showPwd,  setShowPwd]  = useState(false)
  const usernameRef = useRef(null)
  const navigate    = useNavigate()

  useEffect(() => {
    if (sessionStorage.getItem('admin_token')) {
      navigate('/super-admin', { replace: true })
    }
    usernameRef.current?.focus()
  }, [navigate])

  const shake = (msg) => {
    setShaking(true)
    setError(msg)
    setPassword('')
    setTimeout(() => setShaking(false), 500)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!username.trim()) { shake('Username is required'); return }
    if (!password.trim()) { shake('Password is required'); return }

    setLoading(true)
    setError('')

    try {
      const res = await fetch('/api/super-admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password: password.trim() }),
        credentials: 'include',
      })

      if (res.status === 401) {
        shake('Invalid username or password')
        return
      }

      if (!res.ok) {
        shake('Login failed. Please try again.')
        return
      }

      const data = await res.json()

      sessionStorage.setItem('admin_token',    data.token)
      sessionStorage.setItem('admin_username', data.username)
      sessionStorage.setItem('authenticated',  'true')
      sessionStorage.setItem('adminPassword',  password.trim())
      sessionStorage.setItem('login_time',     new Date().toISOString())

      navigate('/super-admin', { replace: true })

    } catch (err) {
      shake('Login failed. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={styles.page}>

      {/* ═══════════════════════════════════ CARD ══════════════════════════ */}
      <div
        className={shaking ? 'animate-shake' : ''}
        style={styles.card}
      >

        {/* ── LEFT PANEL ────────────────────────────────────────────────── */}
        <div style={styles.leftPanel} className="sentinel-card-left">

          {/* Decorative geometric shapes */}
          <div style={{ ...styles.shape, ...styles.shape1 }} />
          <div style={{ ...styles.shape, ...styles.shape2 }} />
          <div style={{ ...styles.shape, ...styles.shape3 }} />
          <div style={{ ...styles.shape, ...styles.shape4 }} />

          {/* Curved white divider on right edge */}
          <div style={styles.curveDivider} />

          {/* Left panel text */}
          <div style={styles.leftContent}>
            <div style={styles.leftIconWrap}>
              <ShieldCheck size={44} color="#fff" strokeWidth={1.5} />
            </div>
            <p style={styles.leftTitle}>SUPER</p>
            <p style={{ ...styles.leftTitle, fontSize: 34 }}>ADMIN</p>
            <p style={styles.leftSubtitle}>PORTAL</p>
          </div>
        </div>

        {/* ── RIGHT PANEL ───────────────────────────────────────────────── */}
        <div style={styles.rightPanel} className="sentinel-card-right">

          {/* Mobile-only header */}
          <div style={styles.mobileHeader} className="mobile-only-header">
            <div style={styles.mobileIconWrap}>
              <ShieldCheck size={28} color="#fff" />
            </div>
            <span style={styles.mobileName}>Super Admin</span>
          </div>

          {/* Avatar circle */}
          <div style={styles.avatarCircle}>
            <User size={32} color="#fff" strokeWidth={2} />
          </div>

          {/* LOGIN heading */}
          <h1 style={styles.loginHeading}>LOGIN</h1>

          {/* Form */}
          <form onSubmit={handleSubmit} style={styles.form} noValidate>

            {/* Username field */}
            <div style={styles.fieldWrap} className="underline-field">
              <User size={18} color="#9CA3AF" style={{ flexShrink: 0 }} />
              <input
                ref={usernameRef}
                type="text"
                placeholder="Username"
                value={username}
                onChange={e => { setUsername(e.target.value); setError('') }}
                autoComplete="username"
                autoCapitalize="none"
                style={styles.underlineInput}
                className="underline-input"
              />
            </div>

            {/* Password field */}
            <div style={styles.fieldWrap} className="underline-field">
              <Lock size={18} color="#9CA3AF" style={{ flexShrink: 0 }} />
              <input
                type={showPwd ? 'text' : 'password'}
                placeholder="PIN / Password"
                value={password}
                onChange={e => { setPassword(e.target.value); setError('') }}
                autoComplete="current-password"
                style={styles.underlineInput}
                className="underline-input"
              />
              <button
                type="button"
                onClick={() => setShowPwd(v => !v)}
                style={styles.eyeBtn}
                tabIndex={-1}
              >
                {showPwd ? <EyeOff size={17} color="#9CA3AF" /> : <Eye size={17} color="#9CA3AF" />}
              </button>
            </div>

            {/* Error message */}
            {error && (
              <p style={styles.errorText}>{error}</p>
            )}

            {/* Login button */}
            <button
              type="submit"
              disabled={loading || !username.trim() || !password.trim()}
              style={{
                ...styles.loginBtn,
                opacity: (loading || !username.trim() || !password.trim()) ? 0.65 : 1,
              }}
              className="login-btn-hover"
            >
              {loading ? 'Verifying…' : 'LOGIN'}
            </button>

          </form>

          {/* Admin login link */}
          <p style={styles.adminLink}>
            Not a super admin?{' '}
            <span
              onClick={() => navigate('/')}
              style={{ color: '#7C3AED', fontWeight: 600, cursor: 'pointer', textDecoration: 'underline' }}
            >
              Admin login →
            </span>
          </p>

          {/* Footer */}
          <p style={styles.footer}>
            SentinelEdge v1.0.0 · Super Admin Portal
          </p>
        </div>
      </div>

      {/* ── Keyframes + responsive ────────────────────────────────────────── */}
      <style>{`
        @keyframes shake {
          0%, 100% { transform: translateX(0); }
          20%       { transform: translateX(-10px); }
          40%       { transform: translateX(10px); }
          60%       { transform: translateX(-7px); }
          80%       { transform: translateX(7px); }
        }
        .animate-shake { animation: shake 0.45s ease-in-out; }

        .underline-input:focus { outline: none; }
        .underline-field:focus-within {
          border-bottom-color: #7C3AED !important;
        }

        .login-btn-hover:hover:not(:disabled) {
          background: #6D28D9 !important;
          transform: translateY(-1px);
          box-shadow: 0 6px 20px rgba(124,58,237,0.4);
        }
        .login-btn-hover { transition: all 0.2s ease; }

        .mobile-only-header { display: none; }

        @media (max-width: 767px) {
          .sentinel-card-left  { display: none !important; }
          .sentinel-card-right {
            border-radius: 0 !important;
            min-height: 100svh !important;
            width: 100% !important;
          }
          .mobile-only-header  { display: flex !important; }
          .sentinel-page {
            background: #1E1B4B !important;
            padding: 0 !important;
          }
          .sentinel-card {
            border-radius: 0 !important;
            flex-direction: column !important;
            max-width: 100% !important;
            min-height: 100svh !important;
          }
        }
      `}</style>
    </div>
  )
}

// ── Styles (identical to LoginPage.jsx, just different text/icon) ─────────────
const styles = {
  page: {
    minHeight: '100svh',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#1E1B4B',
    padding: '1.5rem',
    fontFamily: "'Inter', 'Segoe UI', sans-serif",
  },

  card: {
    display: 'flex',
    flexDirection: 'row',
    width: '100%',
    maxWidth: 900,
    borderRadius: 24,
    overflow: 'hidden',
    boxShadow: '0 25px 60px rgba(0,0,0,0.45)',
    position: 'relative',
    minHeight: 520,
    background: '#fff',
  },

  leftPanel: {
    width: '45%',
    position: 'relative',
    overflow: 'hidden',
    background: 'linear-gradient(135deg, #3B1F8C 0%, #1E1B4B 100%)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },

  shape: {
    position: 'absolute',
    borderRadius: 20,
    pointerEvents: 'none',
  },
  shape1: {
    width: 280, height: 280,
    background: 'rgba(92,53,176,0.45)',
    top: '-60px', left: '-80px',
    transform: 'rotate(-20deg)',
  },
  shape2: {
    width: 220, height: 220,
    background: 'rgba(76,42,158,0.55)',
    bottom: '-50px', left: '-40px',
    transform: 'rotate(-35deg)',
  },
  shape3: {
    width: 200, height: 160,
    background: 'rgba(91,53,176,0.35)',
    top: '45%', right: '-30px',
    transform: 'rotate(-15deg)',
  },
  shape4: {
    width: 160, height: 120,
    background: 'rgba(109,40,217,0.3)',
    top: '10px', right: '20px',
    transform: 'rotate(12deg)',
  },

  curveDivider: {
    position: 'absolute',
    top: 0, right: -40,
    width: 80, height: '100%',
    background: '#fff',
    clipPath: 'ellipse(50% 100% at 100% 50%)',
    zIndex: 2,
  },

  leftContent: {
    position: 'relative',
    zIndex: 3,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 2,
    paddingRight: 32,
  },
  leftIconWrap: {
    marginBottom: 10,
    opacity: 0.9,
  },
  leftTitle: {
    color: '#fff',
    fontSize: 38,
    fontWeight: 900,
    letterSpacing: '0.12em',
    lineHeight: 1,
    margin: 0,
    textShadow: '0 2px 8px rgba(0,0,0,0.3)',
  },
  leftSubtitle: {
    color: 'rgba(255,255,255,0.75)',
    fontSize: 15,
    fontWeight: 600,
    letterSpacing: '0.3em',
    margin: '8px 0 0',
  },

  rightPanel: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '3rem 2.5rem',
    background: '#fff',
    gap: 0,
  },

  mobileHeader: {
    display: 'none',
    alignItems: 'center',
    gap: 10,
    marginBottom: 28,
  },
  mobileIconWrap: {
    width: 42, height: 42,
    borderRadius: 12,
    background: 'linear-gradient(135deg, #7C3AED, #5B21B6)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  mobileName: {
    color: '#1E1B4B',
    fontSize: 20,
    fontWeight: 800,
    letterSpacing: '-0.02em',
  },

  avatarCircle: {
    width: 72, height: 72,
    borderRadius: '50%',
    background: '#7C3AED',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: '0 4px 20px rgba(124,58,237,0.4)',
    marginBottom: 16,
  },

  loginHeading: {
    fontSize: 26,
    fontWeight: 800,
    color: '#1E1B4B',
    letterSpacing: '0.1em',
    margin: '0 0 28px 0',
  },

  form: {
    width: '100%',
    maxWidth: 320,
    display: 'flex',
    flexDirection: 'column',
    gap: 0,
  },

  fieldWrap: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    borderBottom: '2px solid #E5E7EB',
    paddingBottom: 10,
    marginBottom: 24,
    transition: 'border-color 0.2s',
  },

  underlineInput: {
    flex: 1,
    border: 'none',
    outline: 'none',
    background: 'transparent',
    fontSize: 15,
    color: '#111827',
    padding: '4px 0',
  },

  eyeBtn: {
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    padding: '0 2px',
    display: 'flex',
    alignItems: 'center',
    flexShrink: 0,
  },

  errorText: {
    color: '#DC2626',
    fontSize: 13,
    fontWeight: 500,
    textAlign: 'center',
    marginBottom: 12,
    marginTop: -8,
  },

  loginBtn: {
    width: '100%',
    padding: '13px 0',
    background: '#7C3AED',
    color: '#fff',
    border: 'none',
    borderRadius: 10,
    fontSize: 15,
    fontWeight: 700,
    letterSpacing: '0.08em',
    cursor: 'pointer',
    marginTop: 8,
    marginBottom: 20,
  },

  adminLink: {
    color: '#9CA3AF',
    fontSize: 13,
    textAlign: 'center',
    marginBottom: 6,
  },

  footer: {
    color: '#9CA3AF',
    fontSize: 12,
    textAlign: 'center',
    marginTop: 4,
  },
}
