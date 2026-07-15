/**
 * src/components/shared/ConfirmModal.jsx
 *
 * A reusable styled confirmation modal that replaces all window.confirm() calls.
 * Renders with the existing .modal-overlay / .modal-box CSS classes (defined in
 * index.css) so it automatically matches the rest of the dashboard.
 *
 * Props:
 *   isOpen    {boolean}  – controls visibility
 *   title     {string}   – bold heading (e.g. "Delete Sub-Admin")
 *   message   {string}   – body text (the same warning previously passed to window.confirm)
 *   onConfirm {function} – called when the user clicks the destructive action button
 *   onCancel  {function} – called when the user clicks Cancel, presses Escape, or clicks the backdrop
 *   confirmLabel {string} – label for the destructive button (default: "Delete")
 *   cancelLabel  {string} – label for the cancel button (default: "Cancel")
 */
import { useEffect, useRef } from 'react'
import { AlertTriangle } from 'lucide-react'

export default function ConfirmModal({
  isOpen,
  title = 'Are you sure?',
  message,
  onConfirm,
  onCancel,
  confirmLabel = 'Delete',
  cancelLabel = 'Cancel',
}) {
  const cancelBtnRef = useRef(null)

  /* Trap focus on Cancel button when the modal opens (accessibility) */
  useEffect(() => {
    if (isOpen && cancelBtnRef.current) {
      cancelBtnRef.current.focus()
    }
  }, [isOpen])

  /* Close on Escape */
  useEffect(() => {
    if (!isOpen) return
    const handle = (e) => { if (e.key === 'Escape') onCancel() }
    window.addEventListener('keydown', handle)
    return () => window.removeEventListener('keydown', handle)
  }, [isOpen, onCancel])

  if (!isOpen) return null

  return (
    /* Backdrop — clicking it cancels */
    <div className="modal-overlay" onClick={onCancel}>
      {/* Card — stop propagation so clicking inside doesn't dismiss */}
      <div
        className="modal-box"
        style={{ maxWidth: 400 }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Icon + Title */}
        <div className="flex items-start gap-3 mb-4">
          <span
            className="flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center"
            style={{ background: '#fef2f2' }}
          >
            <AlertTriangle size={18} style={{ color: '#ef4444' }} />
          </span>
          <div>
            <h3
              className="font-bold text-gray-900"
              style={{ fontSize: '1rem', lineHeight: '1.4' }}
            >
              {title}
            </h3>
            {message && (
              <p className="text-sm text-gray-500 mt-1" style={{ lineHeight: '1.5' }}>
                {message}
              </p>
            )}
          </div>
        </div>

        {/* Divider */}
        <hr style={{ borderColor: '#f3f4f6', margin: '0 0 1.25rem' }} />

        {/* Action buttons */}
        <div className="flex gap-2 justify-end">
          <button
            ref={cancelBtnRef}
            onClick={onCancel}
            className="btn btn-ghost"
            style={{ minWidth: 80 }}
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            className="btn btn-danger"
            style={{ minWidth: 80 }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
