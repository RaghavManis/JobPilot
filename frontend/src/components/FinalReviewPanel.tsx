import React, { useState, useMemo } from 'react';
import { ApplicationState, api } from '../api/client';

interface Props {
  state: ApplicationState;
  onApproveAndSubmit: () => void;
  isLoading: boolean;
}

interface ReviewFieldItem {
  id: string;
  label: string;
  value: string;
  confidence: number;
  isHumanConfirmed: boolean;
  source: string;
  reason: string;
  isRequired: boolean;
}

export const FinalReviewPanel: React.FC<Props> = ({ state, onApproveAndSubmit, isLoading }) => {
  const [isReviewOpen, setIsReviewOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<'fields' | 'screenshot'>('fields');
  const [screenshotTimestamp, setScreenshotTimestamp] = useState<number>(Date.now());
  const [screenshotLoading, setScreenshotLoading] = useState(false);
  const [screenshotError, setScreenshotError] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');

  // Extract all fields and their filled values from detected_fields and mapped_answers
  const reviewFields: ReviewFieldItem[] = useMemo(() => {
    const items: ReviewFieldItem[] = [];
    const processedIds = new Set<string>();

    if (state.detected_fields && state.detected_fields.length > 0) {
      for (const f of state.detected_fields) {
        if (['button', 'submit', 'reset', 'hidden'].includes((f.input_type || '').toLowerCase())) {
          continue;
        }
        if (f.tag_name === 'button') continue;

        const ansObj = state.mapped_answers?.[f.data_jp_id];
        const val = ansObj?.answer ?? f.current_value ?? '';

        // If not mapped and empty and not required, skip to keep review concise
        if (!val && !f.is_required && !ansObj) continue;

        const isHuman = Boolean(
          ansObj?.source_citations?.includes('human_review') ||
          ansObj?.reason?.toLowerCase().includes('human')
        );

        const label = f.label || f.name || f.placeholder || f.data_jp_id;

        items.push({
          id: f.data_jp_id,
          label,
          value: val || '(Not filled / Optional)',
          confidence: ansObj ? ansObj.confidence : 1.0,
          isHumanConfirmed: isHuman,
          source: ansObj?.source_citations?.join(', ') || (isHuman ? 'Human confirmation' : 'Profile / Form'),
          reason: ansObj?.reason || 'Extracted from user profile',
          isRequired: Boolean(f.is_required)
        });
        processedIds.add(f.data_jp_id);
      }
    }

    if (state.mapped_answers) {
      for (const [key, ans] of Object.entries(state.mapped_answers)) {
        if (!processedIds.has(key)) {
          const isHuman = Boolean(
            ans.source_citations?.includes('human_review') ||
            ans.reason?.toLowerCase().includes('human')
          );
          items.push({
            id: key,
            label: key.replace(/^(field_|jp_)/, '').replace(/_/g, ' '),
            value: ans.answer || '(Not filled)',
            confidence: ans.confidence,
            isHumanConfirmed: isHuman,
            source: ans.source_citations?.join(', ') || (isHuman ? 'Human confirmation' : 'User profile'),
            reason: ans.reason || 'Auto-mapped answer',
            isRequired: false
          });
        }
      }
    }

    if (state.all_completed_fields && state.all_completed_fields.length > 0) {
      for (const item of state.all_completed_fields) {
        const fid = item.field_id || '';
        if (!processedIds.has(fid)) {
          items.push({
            id: fid,
            label: item.label || fid.replace(/^(field_|jp_)/, '').replace(/_/g, ' '),
            value: item.value || '(Not filled)',
            confidence: 1.0,
            isHumanConfirmed: false,
            source: `Step ${item.step || 1} completed`,
            reason: 'Completed in application step',
            isRequired: false
          });
          processedIds.add(fid);
        }
      }
    }

    return items;
  }, [state]);

  const filteredFields = useMemo(() => {
    if (!searchTerm.trim()) return reviewFields;
    const term = searchTerm.toLowerCase();
    return reviewFields.filter(
      f => f.label.toLowerCase().includes(term) || f.value.toLowerCase().includes(term) || f.id.toLowerCase().includes(term)
    );
  }, [reviewFields, searchTerm]);

  const answerCount = reviewFields.length;
  const humanDecisions = reviewFields.filter(f => f.isHumanConfirmed).length;
  const autoFilledCount = answerCount - humanDecisions;

  const handleRefreshScreenshot = () => {
    setScreenshotLoading(true);
    setScreenshotError(false);
    setScreenshotTimestamp(Date.now());
  };

  const screenshotUrl = `${api.getScreenshotUrl(state.application_id)}&ts=${screenshotTimestamp}`;

  return (
    <>
      {/* Main Review Card */}
      <div className="card card-custom p-4 border-left-success">
        <div className="d-flex align-items-center mb-3">
          <span className="badge bg-success me-2 px-3 py-2">Ready For Review</span>
          <h4 className="m-0">Job Application Completed — Final Review</h4>
        </div>

        <p className="text-secondary">
          All form sections and interactive fields have been auto-filled and verified. Explicit user approval is required to click <strong>Submit Application</strong>.
        </p>

        {/* Stats Row */}
        <div className="row my-4 text-center g-3">
          <div className="col-4">
            <div className="p-3 bg-light rounded shadow-sm">
              <h3 className="m-0 text-primary fw-bold">{answerCount}</h3>
              <small className="text-muted fw-semibold">Fields Processed</small>
            </div>
          </div>
          <div className="col-4">
            <div className="p-3 bg-light rounded shadow-sm">
              <h3 className="m-0 text-success fw-bold">{autoFilledCount}</h3>
              <small className="text-muted fw-semibold">Auto-Filled</small>
            </div>
          </div>
          <div className="col-4">
            <div className="p-3 bg-light rounded shadow-sm">
              <h3 className="m-0 text-warning fw-bold">{humanDecisions}</h3>
              <small className="text-muted fw-semibold">Human Confirmed</small>
            </div>
          </div>
        </div>

        {/* Safety Lock Info */}
        <div className="alert alert-info d-flex align-items-center mb-4" role="alert">
          <span className="me-2 fs-5">🔒</span>
          <div>
            <strong>Safety Lock Active:</strong> JobPilot will NOT click submit unless you explicitly approve. Review the filled values or browser preview before proceeding.
          </div>
        </div>

        {/* Action Buttons */}
        <div className="d-flex justify-content-end gap-3 mt-2">
          <button
            type="button"
            className="btn btn-outline-primary px-4 fw-semibold d-flex align-items-center gap-2"
            onClick={() => setIsReviewOpen(true)}
          >
            <span>👁️</span>
            <span>Review Filled Page ({answerCount} Fields)</span>
          </button>
          <button
            type="button"
            className="btn btn-approve d-flex align-items-center gap-2"
            onClick={onApproveAndSubmit}
            disabled={isLoading}
          >
            {isLoading ? (
              <>
                <span className="spinner-border spinner-border-sm" role="status"></span>
                <span>Submitting Application...</span>
              </>
            ) : (
              <>
                <span>🚀</span>
                <span>Approve &amp; Submit Application</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Review Modal Dialog */}
      {isReviewOpen && (
        <div className="review-modal-backdrop" onClick={() => setIsReviewOpen(false)}>
          <div className="review-modal-content" onClick={(e) => e.stopPropagation()}>
            
            {/* Modal Header */}
            <div className="p-4 border-bottom d-flex justify-content-between align-items-center bg-light">
              <div>
                <h5 className="m-0 fw-bold d-flex align-items-center gap-2">
                  <span>📋</span>
                  <span>Application Review — Filled Fields &amp; Live Preview</span>
                </h5>
                <small className="text-muted text-break">
                  Target URL: <a href={state.target_url} target="_blank" rel="noreferrer">{state.target_url}</a>
                </small>
              </div>
              <button
                type="button"
                className="btn-close"
                aria-label="Close"
                onClick={() => setIsReviewOpen(false)}
              ></button>
            </div>

            {/* Navigation Tabs */}
            <div className="px-4 pt-3 border-bottom bg-white d-flex gap-3">
              <button
                type="button"
                className={`btn btn-sm pb-2 fw-semibold border-0 rounded-0 ${
                  activeTab === 'fields'
                    ? 'text-primary border-bottom border-primary border-3'
                    : 'text-secondary'
                }`}
                onClick={() => setActiveTab('fields')}
              >
                📝 Form Fields &amp; Answers ({filteredFields.length})
              </button>
              <button
                type="button"
                className={`btn btn-sm pb-2 fw-semibold border-0 rounded-0 ${
                  activeTab === 'screenshot'
                    ? 'text-primary border-bottom border-primary border-3'
                    : 'text-secondary'
                }`}
                onClick={() => {
                  setActiveTab('screenshot');
                  handleRefreshScreenshot();
                }}
              >
                📸 Live Browser Screenshot
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-4 overflow-auto flex-grow-1" style={{ maxHeight: '60vh' }}>
              
              {/* Tab 1: Form Fields Table */}
              {activeTab === 'fields' && (
                <div>
                  <div className="d-flex justify-content-between align-items-center mb-3">
                    <input
                      type="text"
                      className="form-control form-control-sm w-50"
                      placeholder="Search fields or answers..."
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                    />
                    <span className="text-muted small">
                      Showing {filteredFields.length} of {reviewFields.length} fields
                    </span>
                  </div>

                  {filteredFields.length === 0 ? (
                    <div className="text-center py-5 text-muted">
                      No matching fields found.
                    </div>
                  ) : (
                    <div className="table-responsive">
                      <table className="table table-hover align-middle mb-0">
                        <thead className="table-light">
                          <tr>
                            <th style={{ width: '30%' }}>Field</th>
                            <th style={{ width: '40%' }}>Filled Value</th>
                            <th style={{ width: '15%' }}>Confidence</th>
                            <th style={{ width: '15%' }}>Source</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredFields.map((field) => (
                            <tr key={field.id}>
                              <td>
                                <div className="fw-semibold text-dark">
                                  {field.label}
                                  {field.isRequired && (
                                    <span className="text-danger ms-1" title="Required field">*</span>
                                  )}
                                </div>
                                <code className="text-muted small">{field.id}</code>
                              </td>
                              <td>
                                <div className="p-2 bg-light rounded text-break font-monospace small border">
                                  {field.value}
                                </div>
                                {field.reason && (
                                  <div className="text-muted small mt-1" style={{ fontSize: '0.75rem' }}>
                                    <em>{field.reason}</em>
                                  </div>
                                )}
                              </td>
                              <td>
                                {field.isHumanConfirmed ? (
                                  <span className="badge bg-warning text-dark">
                                    Human Confirmed
                                  </span>
                                ) : (
                                  <span
                                    className={`badge ${
                                      field.confidence >= 0.9
                                        ? 'bg-success'
                                        : field.confidence >= 0.7
                                        ? 'bg-info'
                                        : 'bg-secondary'
                                    }`}
                                  >
                                    {(field.confidence * 100).toFixed(0)}%
                                  </span>
                                )}
                              </td>
                              <td>
                                <span className="badge bg-light text-secondary border">
                                  {field.source}
                                </span>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              {/* Tab 2: Live Browser Screenshot */}
              {activeTab === 'screenshot' && (
                <div className="text-center">
                  <div className="d-flex justify-content-between align-items-center mb-3">
                    <span className="text-muted small">
                      Real-time screenshot rendered by Playwright browser for session: <code className="small">{state.application_id}</code>
                    </span>
                    <div className="d-flex gap-2">
                      <button
                        type="button"
                        className="btn btn-sm btn-outline-secondary"
                        onClick={handleRefreshScreenshot}
                        disabled={screenshotLoading}
                      >
                        {screenshotLoading ? 'Refreshing...' : '🔄 Refresh Screenshot'}
                      </button>
                      <a
                        href={state.target_url}
                        target="_blank"
                        rel="noreferrer"
                        className="btn btn-sm btn-outline-primary"
                      >
                        🔗 Open Form in New Tab
                      </a>
                    </div>
                  </div>

                  <div
                    className="p-3 bg-light rounded border position-relative text-center"
                    style={{ minHeight: '320px' }}
                  >
                    {screenshotLoading && (
                      <div className="p-5 text-muted">
                        <div className="spinner-border text-primary mb-2" role="status"></div>
                        <div>Capturing latest browser view...</div>
                      </div>
                    )}

                    {!screenshotError ? (
                      <img
                        src={screenshotUrl}
                        alt="Application Browser Screenshot"
                        className={`img-fluid rounded border shadow-sm ${screenshotLoading ? 'd-none' : 'd-block'}`}
                        style={{ maxHeight: '500px', margin: '0 auto' }}
                        onLoad={() => setScreenshotLoading(false)}
                        onError={() => {
                          setScreenshotLoading(false);
                          setScreenshotError(true);
                        }}
                      />
                    ) : (
                      <div className="py-5 text-muted">
                        <p className="fs-1 m-0">📸</p>
                        <p className="fw-semibold">Could not capture live browser screenshot.</p>
                        <p className="small">
                          The browser might be running headful or the page finished loading. You can review all extracted fields in the <strong>Form Fields &amp; Answers</strong> tab or open the original page URL.
                        </p>
                        <button
                          type="button"
                          className="btn btn-sm btn-primary mt-2"
                          onClick={handleRefreshScreenshot}
                        >
                          Retry Screenshot
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              )}

            </div>

            {/* Modal Footer */}
            <div className="p-3 border-top bg-light d-flex justify-content-between align-items-center">
              <button
                type="button"
                className="btn btn-outline-secondary px-4"
                onClick={() => setIsReviewOpen(false)}
              >
                Close Review
              </button>
              <div className="d-flex gap-2">
                <button
                  type="button"
                  className="btn btn-approve px-4 d-flex align-items-center gap-2"
                  onClick={() => {
                    setIsReviewOpen(false);
                    onApproveAndSubmit();
                  }}
                  disabled={isLoading}
                >
                  {isLoading ? (
                    <>
                      <span className="spinner-border spinner-border-sm" role="status"></span>
                      <span>Submitting Application...</span>
                    </>
                  ) : (
                    <>
                      <span>🚀</span>
                      <span>Approve &amp; Submit Application</span>
                    </>
                  )}
                </button>
              </div>
            </div>

          </div>
        </div>
      )}
    </>
  );
};
