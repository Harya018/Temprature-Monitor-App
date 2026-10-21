/**
 * src/components/dashboard/DashTile.jsx
 * Shared shell for every dashboard stat/sensor tile so they all line up:
 * header (icon + label | badge), big value + unit, caption, optional extra,
 * footer pinned to the bottom. Height comes from the parent grid (h-full).
 *
 * Props:
 *   icon, iconColor : lucide-react component + colour for the header icon
 *   label           : header text
 *   badge           : node shown top-right (usually <Badge />)
 *   value           : string | number | null — null/'—' renders a muted dash
 *   valueColor      : colour for the value
 *   unit            : small text after the value
 *   caption         : one line under the value
 *   children        : optional extra block (breach banner, range chip …)
 *   footerLeft/Right: footer texts
 *   className       : extra classes on the card (borders, animations)
 */
export default function DashTile({
  icon: Icon, iconColor = '#7C3AED', label, badge,
  value, valueColor = '#1F2937', unit, caption,
  children, footerLeft, footerRight, className = '', valueKey,
}) {
  const empty = value === null || value === undefined || value === '' || value === '—'
  return (
    <div className={`card dash-tile p-5 flex flex-col gap-3 h-full transition-all duration-500 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between gap-2 min-h-[28px]">
        <div className="flex items-center gap-2 min-w-0">
          {Icon && <Icon size={18} style={{ color: iconColor, flexShrink: 0 }} />}
          <span className="text-sm font-semibold text-gray-700 truncate">{label}</span>
        </div>
        {badge}
      </div>

      {/* Value */}
      <div className="flex items-baseline gap-1.5 min-w-0">
        <span
          key={valueKey}
          className={`tile-value ${valueKey !== undefined ? 'animate-pulse-num' : ''}`}
          style={{ color: empty ? '#D1D5DB' : valueColor }}
        >
          {empty ? '—' : value}
        </span>
        {unit && <span className="text-lg font-semibold text-gray-400">{unit}</span>}
      </div>

      {/* Caption */}
      <p className="text-xs text-gray-500 min-h-[16px] -mt-1 truncate">{caption}</p>

      {children}

      {/* Footer */}
      <div className="flex items-center justify-between gap-2 mt-auto pt-2 border-t border-gray-100">
        <span className="text-xs text-gray-400 truncate">{footerLeft}</span>
        <span className="text-xs text-gray-400 whitespace-nowrap">{footerRight}</span>
      </div>
    </div>
  )
}
