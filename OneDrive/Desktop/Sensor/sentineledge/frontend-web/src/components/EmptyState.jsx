export default function EmptyState({ icon: Icon, title, description, className = '' }) {
  return (
    <div className={`flex flex-col items-center gap-3 py-12 px-4 text-center text-gray-400 ${className}`}>
      {Icon && <Icon size={36} className="text-gray-300" />}
      {title && <p className="font-medium text-gray-500">{title}</p>}
      {description && <p className="text-xs">{description}</p>}
    </div>
  )
}
