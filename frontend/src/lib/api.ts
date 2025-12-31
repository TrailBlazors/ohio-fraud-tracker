/**
 * API client for Ohio Fraud Tracker backend
 */

// In production (Vercel), API is on same domain so use relative path
// In development, use localhost:8000
const API_URL = import.meta.env.PUBLIC_API_URL || (import.meta.env.DEV ? 'http://localhost:8000' : '');

export interface Award {
  id: number;
  source: string;
  award_type: string;
  amount: number;
  description: string | null;
  recipient_name: string;
  recipient_city: string | null;
  agency_code: string | null;
  agency_name: string | null;
  award_date: string | null;
  cfda_number: string | null;
}

export interface Recipient {
  id: number;
  name: string;
  city: string | null;
  state: string;
  zip_code: string | null;
  business_status: string;
  total_awards: number;
  total_amount: number;
}

export interface AgencySummary {
  id: number;
  code: string;
  name: string;
  total_awards: number;
  total_amount: number;
}

export interface DashboardStats {
  total_awards: number;
  total_amount: number;
  total_recipients: number;
  total_flagged: number;
  correlation_status: string;  // not_run, run, no_data
  awards_by_type: Record<string, { count: number; total: number }>;
  awards_by_source: Record<string, { count: number; total: number }>;
  top_agencies: AgencySummary[];
  recent_awards: Award[];
}

export interface PaginatedResponse<T> {
  items: T[];
  page: number;
  page_size: number;
  total_count: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
}

export interface SearchParams {
  q?: string;
  agency_code?: string;
  award_type?: string;
  source?: string;
  city?: string;
  min_amount?: number;
  max_amount?: number;
  start_date?: string;
  end_date?: string;
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
}

/**
 * Make API request with error handling
 */
async function apiRequest<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_URL}${endpoint}`;
  
  try {
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });
    
    if (!response.ok) {
      throw new Error(`API error: ${response.status} ${response.statusText}`);
    }
    
    return response.json();
  } catch (error) {
    console.error(`API request failed: ${endpoint}`, error);
    throw error;
  }
}

/**
 * Build query string from params object
 */
function buildQueryString(params: Record<string, any>): string {
  const searchParams = new URLSearchParams();
  
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      searchParams.append(key, String(value));
    }
  }
  
  const query = searchParams.toString();
  return query ? `?${query}` : '';
}

// =============================================================================
// API METHODS
// =============================================================================

/**
 * Get dashboard statistics
 */
export async function getStats(): Promise<DashboardStats> {
  return apiRequest<DashboardStats>('/api/stats');
}

/**
 * Get awards with filtering and pagination
 */
export async function getAwards(params: SearchParams = {}): Promise<PaginatedResponse<Award>> {
  const query = buildQueryString(params);
  return apiRequest<PaginatedResponse<Award>>(`/api/awards${query}`);
}

/**
 * Get grants only
 */
export async function getGrants(params: SearchParams = {}): Promise<PaginatedResponse<Award>> {
  const query = buildQueryString(params);
  return apiRequest<PaginatedResponse<Award>>(`/api/grants${query}`);
}

/**
 * Get loans only
 */
export async function getLoans(params: SearchParams = {}): Promise<PaginatedResponse<Award>> {
  const query = buildQueryString(params);
  return apiRequest<PaginatedResponse<Award>>(`/api/loans${query}`);
}

/**
 * Get single award by ID
 */
export async function getAward(id: number): Promise<Award> {
  return apiRequest<Award>(`/api/awards/${id}`);
}

/**
 * Get recipients with filtering and pagination
 */
export async function getRecipients(params: SearchParams = {}): Promise<PaginatedResponse<Recipient>> {
  const query = buildQueryString(params);
  return apiRequest<PaginatedResponse<Recipient>>(`/api/recipients${query}`);
}

/**
 * Get single recipient by ID
 */
export async function getRecipient(id: number): Promise<Recipient> {
  return apiRequest<Recipient>(`/api/recipients/${id}`);
}

/**
 * Get awards for a specific recipient
 */
export async function getRecipientAwards(id: number, params: SearchParams = {}): Promise<PaginatedResponse<Award>> {
  const query = buildQueryString(params);
  return apiRequest<PaginatedResponse<Award>>(`/api/recipients/${id}/awards${query}`);
}

/**
 * Get flagged recipients
 */
export async function getFlaggedRecipients(params: SearchParams = {}): Promise<PaginatedResponse<any>> {
  const query = buildQueryString(params);
  return apiRequest<PaginatedResponse<any>>(`/api/recipients/flagged${query}`);
}

/**
 * Get all agencies with stats
 */
export async function getAgencies(): Promise<AgencySummary[]> {
  return apiRequest<AgencySummary[]>('/api/stats/agencies');
}

/**
 * Get stats by year
 */
export async function getStatsByYear(): Promise<{ year: string; count: number; total: number }[]> {
  return apiRequest<{ year: string; count: number; total: number }[]>('/api/stats/by-year');
}

/**
 * Get stats by city
 */
export async function getStatsByCity(limit = 20): Promise<{ city: string; count: number; total: number }[]> {
  return apiRequest<{ city: string; count: number; total: number }[]>(`/api/stats/by-city?limit=${limit}`);
}

/**
 * Run correlation analysis
 */
export async function runCorrelation(): Promise<{ success: boolean; flags_found: number; flags_saved: number; error?: string }> {
  return apiRequest<{ success: boolean; flags_found: number; flags_saved: number; error?: string }>('/api/correlation/run', {
    method: 'POST',
  });
}

/**
 * Get fraud flags summary
 */
export async function getFlagsSummary(): Promise<{
  total_flags: number;
  unresolved: number;
  resolved: number;
  by_severity: Record<string, number>;
  by_type: Record<string, number>;
}> {
  return apiRequest('/api/correlation/flags/summary');
}

/**
 * Search recipients (autocomplete)
 */
export async function searchRecipients(q: string, limit = 10): Promise<{ id: number; name: string; city: string }[]> {
  return apiRequest<{ id: number; name: string; city: string }[]>(`/api/recipients/search/autocomplete?q=${encodeURIComponent(q)}&limit=${limit}`);
}

// =============================================================================
// UTILITY FUNCTIONS
// =============================================================================

/**
 * Format currency amount
 */
export function formatCurrency(amount: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

/**
 * Format large numbers with abbreviations
 */
export function formatNumber(num: number): string {
  if (num >= 1_000_000_000) {
    return `${(num / 1_000_000_000).toFixed(1)}B`;
  }
  if (num >= 1_000_000) {
    return `${(num / 1_000_000).toFixed(1)}M`;
  }
  if (num >= 1_000) {
    return `${(num / 1_000).toFixed(1)}K`;
  }
  return num.toLocaleString();
}

/**
 * Format date string
 */
export function formatDate(dateStr: string | null): string {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

// =============================================================================
// AWARD TYPE HELPERS
// =============================================================================

/** Award type configuration with display name, chip class, and icon */
const AWARD_TYPE_CONFIG: Record<string, { name: string; chipClass: string; icon: string }> = {
  block_grant: { name: 'Block Grant', chipClass: 'chip-grant', icon: '🏛️' },
  formula_grant: { name: 'Formula Grant', chipClass: 'chip-grant', icon: '📊' },
  project_grant: { name: 'Project Grant', chipClass: 'chip-grant', icon: '📋' },
  cooperative_agreement: { name: 'Cooperative', chipClass: 'chip-cooperative', icon: '🤝' },
  direct_loan: { name: 'Direct Loan', chipClass: 'chip-loan', icon: '💵' },
  guaranteed_loan: { name: 'Guaranteed Loan', chipClass: 'chip-loan', icon: '🔒' },
  direct_payment: { name: 'Direct Payment', chipClass: 'chip-payment', icon: '💳' },
  insurance: { name: 'Insurance', chipClass: 'chip-insurance', icon: '🛡️' },
  contract: { name: 'Contract', chipClass: 'chip-contract', icon: '📝' },
  loan: { name: 'PPP Loan', chipClass: 'chip-loan', icon: '💰' },
  other: { name: 'Other', chipClass: 'chip-other', icon: '📄' },
};

/**
 * Get award type display name
 */
export function getAwardTypeName(type: string): string {
  return AWARD_TYPE_CONFIG[type]?.name || type;
}

/**
 * Get chip class for award type
 */
export function getAwardTypeChipClass(type: string): string {
  return AWARD_TYPE_CONFIG[type]?.chipClass || 'chip-other';
}

/**
 * Get icon for award type
 */
export function getAwardTypeIcon(type: string): string {
  return AWARD_TYPE_CONFIG[type]?.icon || '📄';
}

/**
 * Get badge color class for award type (legacy support)
 */
export function getAwardTypeBadgeClass(type: string): string {
  if (type.includes('grant')) return 'badge-success';
  if (type.includes('loan')) return 'badge-info';
  if (type.includes('contract')) return 'badge-warning';
  return 'badge-info';
}

// =============================================================================
// AGENCY HELPERS
// =============================================================================

/** Agency code to chip class mapping */
const AGENCY_CHIP_CLASSES: Record<string, string> = {
  HHS: 'chip-agency-hhs',
  ED: 'chip-agency-ed',
  DOT: 'chip-agency-dot',
  HUD: 'chip-agency-hud',
  USDA: 'chip-agency-usda',
  DOJ: 'chip-agency-doj',
  DOL: 'chip-agency-dol',
  SBA: 'chip-agency-sba',
  EPA: 'chip-agency-epa',
  DOE: 'chip-agency-doe',
  VA: 'chip-agency-va',
  DHS: 'chip-agency-dhs',
};

/**
 * Get chip class for agency code
 */
export function getAgencyChipClass(agencyCode: string | null): string {
  if (!agencyCode) return 'chip-agency';
  return AGENCY_CHIP_CLASSES[agencyCode.toUpperCase()] || 'chip-agency';
}

// =============================================================================
// SOURCE HELPERS
// =============================================================================

/**
 * Get source display name
 */
export function getSourceName(source: string): string {
  const sourceNames: Record<string, string> = {
    usaspending: 'USAspending',
    sba_ppp: 'SBA PPP',
    ohio_checkbook: 'Ohio Checkbook',
  };
  return sourceNames[source] || source;
}

/**
 * Get chip class for data source
 */
export function getSourceChipClass(source: string): string {
  const sourceClasses: Record<string, string> = {
    usaspending: 'chip-source-usaspending',
    sba_ppp: 'chip-source-ppp',
  };
  return sourceClasses[source] || 'chip-source';
}

// =============================================================================
// BUSINESS STATUS HELPERS
// =============================================================================

/**
 * Get chip class for business status
 */
export function getStatusChipClass(status: string): string {
  const statusClasses: Record<string, string> = {
    active: 'chip-status-active',
    inactive: 'chip-status-inactive',
    dissolved: 'chip-status-inactive',
    unknown: 'chip-status-unknown',
  };
  return statusClasses[status?.toLowerCase()] || 'chip-status-unknown';
}

/**
 * Get icon for business status
 */
export function getStatusIcon(status: string): string {
  const statusIcons: Record<string, string> = {
    active: '✓',
    inactive: '✗',
    dissolved: '✗',
    unknown: '?',
  };
  return statusIcons[status?.toLowerCase()] || '?';
}
