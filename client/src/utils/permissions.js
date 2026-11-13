// Role hierarchy (see server/schema.sql's users.role CHECK constraint):
// Owner > Admin > Editor > Viewer. Owner is grouped with Admin wherever the
// backend already does so (main.py's _CAN_VIEW_ALL_PROJECTS_ROLES) -- it's
// the most-privileged role, so it should never be MORE restricted than Admin.

// Can see/use the "Check Health Project" menu (Connect Git/Jira, Upload
// ZIP/Excel) and trigger scans (e.g. the Project List's Re-check button).
export const CHECK_HEALTH_ROLES = ['Owner', 'Admin', 'Editor']

// Can see/use the "Member Management" page (invite members, change roles).
export const MEMBER_MANAGEMENT_ROLES = ['Owner', 'Admin']

// Can see/use the "Model Configuration" page (LLM API key/base URL/model
// name for both evaluation phases) -- same access level as Member
// Management, since it's system-level config with cost/security impact.
export const MODEL_CONFIG_ROLES = ['Owner', 'Admin']

// Can see/use the "Member Performance" page (cross-project rollup per
// assignee) -- same access level as Member Management, since it surfaces
// other people's performance data across every project, not just the
// viewer's own.
export const MEMBER_PERFORMANCE_ROLES = ['Owner', 'Admin']

export function canAccessCheckHealth(role) {
  return CHECK_HEALTH_ROLES.includes(role)
}

export function canManageMembers(role) {
  return MEMBER_MANAGEMENT_ROLES.includes(role)
}

export function canManageModelConfig(role) {
  return MODEL_CONFIG_ROLES.includes(role)
}

export function canViewMemberPerformance(role) {
  return MEMBER_PERFORMANCE_ROLES.includes(role)
}
