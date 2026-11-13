/** "assignee-test" -> "AT", "Nguyen Xuan Chien" -> "NX": first letter of the
 * first two whitespace/hyphen-separated tokens, uppercased. Falls back to
 * the first two characters for a single-word name. */
export function getInitials(name) {
  const tokens = (name || '').trim().split(/[\s-]+/).filter(Boolean)
  if (tokens.length === 0) return '?'
  if (tokens.length === 1) return tokens[0].slice(0, 2).toUpperCase()
  return (tokens[0][0] + tokens[1][0]).toUpperCase()
}

// Fixed palette so the same project name always maps to the same color.
const PROJECT_AVATAR_PALETTE = [
  { bg: 'bg-red-500', text: 'text-white' },
  { bg: 'bg-violet-500', text: 'text-white' },
  { bg: 'bg-emerald-500', text: 'text-white' },
  { bg: 'bg-amber-600', text: 'text-white' },
  { bg: 'bg-teal-500', text: 'text-white' },
  { bg: 'bg-indigo-500', text: 'text-white' },
  { bg: 'bg-pink-500', text: 'text-white' },
  { bg: 'bg-blue-500', text: 'text-white' },
]

function hashString(str) {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = (hash * 31 + str.charCodeAt(i)) | 0
  }
  return Math.abs(hash)
}

/** Deterministic { bg, text } Tailwind class pair for a project avatar,
 * hashed from its name so the color is stable across renders/reloads. */
export function getProjectAvatarClass(name) {
  const idx = hashString(name || '') % PROJECT_AVATAR_PALETTE.length
  return PROJECT_AVATAR_PALETTE[idx]
}

// Checker/user avatars all share one look (unlike project avatars).
export const CHECKER_AVATAR_CLASS = { bg: 'bg-indigo-100', text: 'text-indigo-600' }
