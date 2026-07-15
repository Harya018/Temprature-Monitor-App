/**
 * SubscriberManager.jsx — Manage alert notification subscribers.
 * Shows escalation order, push status; add/delete subscribers.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { fetchSubscribers, addSubscriber, deleteSubscriber } from '../services/api';
import ConfirmModal from './shared/ConfirmModal';

const ORDER_LABELS = {
  1: { label: 'Primary', color: 'text-danger bg-danger/10 border-danger/30' },
  2: { label: 'Escalation 2', color: 'text-warning bg-warning/10 border-warning/30' },
  3: { label: 'Final', color: 'text-orange-400 bg-orange-500/10 border-orange-500/30' },
};

export default function SubscriberManager() {
  const [open, setOpen] = useState(false);
  const [subscribers, setSubscribers] = useState([]);
  const [form, setForm] = useState({ name: '', phone: '', email: '', escalation_order: 1 });
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState('');
  const [confirmId, setConfirmId] = useState(null); // subscriber id pending deletion

  const load = useCallback(() => {
    fetchSubscribers()
      .then(setSubscribers)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  const handleAdd = async (e) => {
    e.preventDefault();
    setAdding(true);
    setError('');
    try {
      await addSubscriber({
        name: form.name.trim(),
        phone: form.phone.trim(),
        email: form.email.trim(),
        escalation_order: Number(form.escalation_order),
      });
      setForm({ name: '', phone: '', email: '', escalation_order: 1 });
      load();
    } catch (err) {
      setError(err.message || 'Failed to add subscriber');
    } finally {
      setAdding(false);
    }
  };

  // Step 1: open the confirmation modal
  const handleDeleteClick = (id) => {
    setConfirmId(id);
  };

  // Step 2: user confirmed — run the actual delete
  const handleDeleteConfirm = async () => {
    const id = confirmId;
    setConfirmId(null);
    try {
      await deleteSubscriber(id);
      load();
    } catch (err) {
      setError('Failed to delete: ' + (err.message || 'Unknown error'));
    }
  };

  return (
    <div className="bg-card rounded-2xl ring-1 ring-white/5 overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-6 py-4 hover:bg-white/5 transition-colors"
      >
        <span className="text-sm font-semibold text-text-secondary uppercase tracking-widest">
          👥 Subscriber Management
        </span>
        <svg
          className={`w-4 h-4 text-text-secondary transition-transform duration-300 ${open ? 'rotate-180' : ''}`}
          fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="px-6 pb-6 space-y-5">
          {/* Subscriber table */}
          {subscribers.length === 0 ? (
            <p className="text-text-secondary text-sm text-center py-4">
              No subscribers configured. Add one below.
            </p>
          ) : (
            <div className="overflow-x-auto -mx-2">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-text-secondary text-xs uppercase tracking-widest border-b border-white/5">
                    <th className="text-left py-2 px-2">Order</th>
                    <th className="text-left py-2 px-2">Name</th>
                    <th className="text-left py-2 px-2 hidden sm:table-cell">Phone</th>
                    <th className="text-left py-2 px-2 hidden md:table-cell">Email</th>
                    <th className="text-left py-2 px-2">Push</th>
                    <th className="py-2 px-2" />
                  </tr>
                </thead>
                <tbody>
                  {subscribers.map((s) => {
                    const orderInfo = ORDER_LABELS[s.escalation_order] || {
                      label: `#${s.escalation_order}`,
                      color: 'text-text-secondary bg-white/5 border-white/10',
                    };
                    return (
                      <tr key={s.id} className="border-b border-white/5 hover:bg-white/3 transition-colors">
                        <td className="py-2.5 px-2">
                          <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${orderInfo.color}`}>
                            {orderInfo.label}
                          </span>
                        </td>
                        <td className="py-2.5 px-2 text-text-primary font-medium">{s.name}</td>
                        <td className="py-2.5 px-2 text-text-secondary hidden sm:table-cell">{s.phone}</td>
                        <td className="py-2.5 px-2 text-text-secondary hidden md:table-cell truncate max-w-[150px]">
                          {s.email}
                        </td>
                        <td className="py-2.5 px-2">
                          <span
                            title={s.has_push_subscription ? 'Push subscription registered' : 'No push subscription'}
                            className={`inline-block w-2.5 h-2.5 rounded-full ${s.has_push_subscription ? 'bg-success' : 'bg-white/20'}`}
                          />
                        </td>
                        <td className="py-2.5 px-2 text-right">
                          <button
                            onClick={() => handleDeleteClick(s.id)}
                            className="text-xs text-danger hover:text-danger/80 font-medium transition-colors"
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Add subscriber form */}
          <form onSubmit={handleAdd} className="space-y-3 border-t border-white/5 pt-4">
            <p className="text-xs text-text-secondary font-semibold uppercase tracking-widest">
              Add Subscriber
            </p>
            <div className="grid grid-cols-2 gap-3">
              {[
                { key: 'name', label: 'Name', type: 'text', placeholder: 'Alice' },
                { key: 'phone', label: 'Phone (E.164)', type: 'tel', placeholder: '+1234567890' },
                { key: 'email', label: 'Email', type: 'email', placeholder: 'alice@example.com' },
              ].map(({ key, label, type, placeholder }) => (
                <div key={key} className={key === 'email' ? 'col-span-2' : ''}>
                  <label className="text-xs text-text-secondary mb-1 block">{label}</label>
                  <input
                    type={type}
                    required
                    placeholder={placeholder}
                    value={form[key]}
                    onChange={(e) => setForm((v) => ({ ...v, [key]: e.target.value }))}
                    className="w-full bg-bg border border-white/10 rounded-lg px-3 py-2 text-sm
                               text-text-primary placeholder-text-secondary/50
                               focus:outline-none focus:border-primary transition-colors"
                  />
                </div>
              ))}
              <div>
                <label className="text-xs text-text-secondary mb-1 block">Escalation Order</label>
                <select
                  value={form.escalation_order}
                  onChange={(e) => setForm((v) => ({ ...v, escalation_order: e.target.value }))}
                  className="w-full bg-bg border border-white/10 rounded-lg px-3 py-2 text-sm
                             text-text-primary focus:outline-none focus:border-primary transition-colors"
                >
                  <option value={1}>1 — Primary (first alerted)</option>
                  <option value={2}>2 — Escalation</option>
                  <option value={3}>3 — Final escalation</option>
                </select>
              </div>
            </div>

            {error && (
              <p className="text-xs text-danger bg-danger/10 border border-danger/30 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={adding}
              className="w-full py-2.5 rounded-lg bg-primary hover:bg-primary/80 text-white
                         font-semibold text-sm transition-colors disabled:opacity-50"
            >
              {adding ? 'Adding…' : 'Add Subscriber'}
            </button>
          </form>
        </div>
      )}
      <ConfirmModal
        isOpen={confirmId !== null}
        title="Remove Subscriber"
        message="Remove this subscriber? They will no longer receive alert notifications."
        confirmLabel="Remove"
        cancelLabel="Cancel"
        onConfirm={handleDeleteConfirm}
        onCancel={() => setConfirmId(null)}
      />
    </div>
  );
}
