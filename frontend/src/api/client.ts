const API_BASE = 'http://localhost:8000';

export interface ApplicationSession {
  id: string;
  user_id: string;
  target_url: string;
  status: string;
  current_page_title?: string;
  current_url?: string;
  submission_approved: boolean;
}

export interface FormField {
  data_jp_id: string;
  tag_name: string;
  input_type?: string;
  name?: string;
  element_id?: string;
  placeholder?: string;
  label?: string;
  visible_text?: string;
  is_required: boolean;
  is_visible: boolean;
  current_value?: string;
  options: string[];
}

export interface ConfidenceResult {
  field_id: string;
  answer?: string;
  confidence: number;
  reason: string;
  source_citations: string[];
  requires_human_input: boolean;
  question_text?: string;
  section_heading?: string;
  helper_text?: string;
  field_type?: string;
  options?: string[];
  is_required?: boolean;
}

export interface ApplicationState {
  application_id: string;
  user_id: string;
  target_url: string;
  current_url?: string;
  current_page_title?: string;
  status: string;
  login_required: boolean;
  login_completed: boolean;
  page_type?: string;
  auth_category?: string;
  auth_details?: string;
  detected_fields?: FormField[];
  mapped_answers: Record<string, ConfidenceResult>;
  human_review_queue: ConfidenceResult[];
  validation_errors: string[];
  submission_approved: boolean;
  total_fields_filled?: number;
  all_completed_fields?: any[];
  error_message?: string;
}

export const api = {
  getScreenshotUrl(sessionId: string): string {
    return `${API_BASE}/api/agent/${sessionId}/screenshot?t=${Date.now()}`;
  },
  async healthCheck() {
    const res = await fetch(`${API_BASE}/health`);
    return res.json();
  },

  async createSession(targetUrl: string, userId: string = 'user_default'): Promise<ApplicationSession> {
    const res = await fetch(`${API_BASE}/api/sessions/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, target_url: targetUrl })
    });
    if (!res.ok) throw new Error('Failed to create session');
    return res.json();
  },

  async runStep(sessionId: string): Promise<ApplicationState> {
    const res = await fetch(`${API_BASE}/api/agent/${sessionId}/step`, {
      method: 'POST'
    });
    if (!res.ok) throw new Error('Failed to execute workflow step');
    return res.json();
  },

  async getState(sessionId: string): Promise<ApplicationState> {
    const res = await fetch(`${API_BASE}/api/agent/${sessionId}/state`);
    if (!res.ok) throw new Error('Failed to fetch state');
    return res.json();
  },

  async completeLogin(sessionId: string): Promise<ApplicationState> {
    const res = await fetch(`${API_BASE}/api/agent/${sessionId}/login-complete`, {
      method: 'POST'
    });
    if (!res.ok) throw new Error('Failed to complete login');
    return res.json();
  },

  async approveSubmission(sessionId: string): Promise<ApplicationState> {
    const res = await fetch(`${API_BASE}/api/agent/${sessionId}/approve-submission`, {
      method: 'POST'
    });
    if (!res.ok) throw new Error('Failed to approve submission');
    return res.json();
  },

  async submitHumanReview(sessionId: string, answers: Record<string, string>): Promise<ApplicationState> {
    const res = await fetch(`${API_BASE}/api/agent/${sessionId}/human-review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to submit review' }));
      throw new Error(err.detail || 'Failed to submit human review');
    }
    return res.json();
  },

  async pause(sessionId: string): Promise<ApplicationState> {
    const res = await fetch(`${API_BASE}/api/agent/${sessionId}/pause`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to pause workflow');
    return res.json();
  },

  async resume(sessionId: string): Promise<ApplicationState> {
    const res = await fetch(`${API_BASE}/api/agent/${sessionId}/resume`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to resume workflow');
    return res.json();
  },

  async stop(sessionId: string) {
    const res = await fetch(`${API_BASE}/api/agent/${sessionId}/stop`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to stop workflow');
    return res.json();
  },

  async focusBrowser(sessionId: string): Promise<{ status: string; message: string; detail?: string; page_title?: string }> {
    const res = await fetch(`${API_BASE}/api/agent/${sessionId}/focus-browser`, { method: 'POST' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to bring browser to front' }));
      throw new Error(err.detail || err.message || 'Failed to bring browser to front');
    }
    return res.json();
  },

  createEventSource(sessionId: string): EventSource {
    return new EventSource(`${API_BASE}/api/agent/${sessionId}/events`);
  },

  async getProfile(userId: string = 'user_default') {
    const res = await fetch(`${API_BASE}/api/profile/?user_id=${userId}`);
    if (!res.ok) throw new Error('Failed to fetch profile');
    return res.json();
  },

  async uploadPhoto(file: File, userId: string = 'user_default') {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_BASE}/api/profile/photo?user_id=${userId}`, {
      method: 'POST',
      body: formData
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Failed to upload photo' }));
      throw new Error(err.detail || 'Failed to upload photo');
    }
    return res.json();
  }
};
