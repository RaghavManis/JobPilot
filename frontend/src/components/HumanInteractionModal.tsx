import React, { useState } from 'react';
import { ConfidenceResult } from '../api/client';

interface Props {
  questions: ConfidenceResult[];
  onComplete: (answers: Record<string, string>) => void;
}

export const HumanInteractionModal: React.FC<Props> = ({ questions, onComplete }) => {
  // Seed state with suggested answers
  const [answers, setAnswers] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const q of questions) {
      if (q.answer) {
        if (Array.isArray(q.options) && q.options.length > 0) {
          const lowerAns = q.answer.trim().toLowerCase();
          const validOpt = q.options.find(opt => {
            const oLower = opt.trim().toLowerCase();
            return oLower === lowerAns || oLower.includes(lowerAns) || lowerAns.includes(oLower);
          });
          if (validOpt) {
            initial[q.field_id] = validOpt;
          }
        } else {
          initial[q.field_id] = q.answer;
        }
      }
    }
    return initial;
  });

  const [validationError, setValidationError] = useState<string | null>(null);

  const handleChange = (fieldId: string, val: string) => {
    setValidationError(null);
    setAnswers(prev => ({ ...prev, [fieldId]: val }));
  };

  const handleAcceptSuggested = (q: ConfidenceResult) => {
    if (q.answer) {
      if (Array.isArray(q.options) && q.options.length > 0) {
        const lowerAns = q.answer.trim().toLowerCase();
        const validOpt = q.options.find(opt => {
          const oLower = opt.trim().toLowerCase();
          return oLower === lowerAns || oLower.includes(lowerAns) || lowerAns.includes(oLower);
        });
        if (validOpt) {
          setValidationError(null);
          setAnswers(prev => ({ ...prev, [q.field_id]: validOpt }));
        }
      } else {
        setValidationError(null);
        setAnswers(prev => ({ ...prev, [q.field_id]: q.answer! }));
      }
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    // Check required fields & option validity
    for (const q of questions) {
      const val = answers[q.field_id];
      if (q.is_required && (!val || !val.trim())) {
        const title = q.question_text || q.field_id;
        const msg = `"${title}" is a required field. Please provide an answer or select an option.`;
        console.warn("HumanInteractionModal validation warning:", msg);
        setValidationError(msg);
        return;
      }

      if (val && Array.isArray(q.options) && q.options.length > 0) {
        const isMulti = q.field_type === 'checkbox_group' || q.field_type === 'multiselect';
        if (!isMulti) {
          const lowerAns = val.trim().toLowerCase();
          const validOpt = q.options.find(opt => {
            const oLower = opt.trim().toLowerCase();
            return oLower === lowerAns || oLower.includes(lowerAns) || lowerAns.includes(oLower);
          });
          if (!validOpt) {
            const title = q.question_text || q.field_id;
            const msg = `"${val}" is not a valid option for "${title}". Please choose one of: ${q.options.join(', ')}`;
            setValidationError(msg);
            return;
          }
        }
      }
    }

    console.log("HumanInteractionModal: Submitting human review answers:", answers);
    setValidationError(null);
    onComplete(answers);
  };

  if (!questions || questions.length === 0) return null;

  return (
    <div className="card card-custom p-4 border-left-warning mb-4 shadow-sm">
      <div className="d-flex align-items-center justify-content-between mb-3">
        <div className="d-flex align-items-center gap-2">
          <span className="badge bg-warning text-dark px-3 py-2 fs-6">Human Input Required</span>
          <h4 className="m-0 fw-bold">Application Form Questions</h4>
        </div>
        <span className="badge bg-secondary">{questions.length} Question{questions.length > 1 ? 's' : ''} Remaining</span>
      </div>

      <p className="text-muted small mb-4">
        JobPilot encountered questions requiring human confirmation (e.g. options selection, missing facts, or sensitive preferences). 
        Review the actual application questions below to resume automated filling.
      </p>

      {validationError && (
        <div className="alert alert-danger py-2 px-3 small d-flex align-items-center gap-2 mb-3">
          <span>⚠️</span>
          <span>{validationError}</span>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        {questions.map((q, idx) => {
          const title = q.question_text || `Field ${q.field_id}`;
          const currentVal = answers[q.field_id] ?? '';
          const hasOptions = Array.isArray(q.options) && q.options.length > 0;
          const isCheckboxGroup = q.field_type === 'checkbox_group' || q.field_type === 'multiselect';
          const isRadio = q.field_type === 'radio';
          const isSelect = q.field_type === 'select' || (hasOptions && !isRadio && !isCheckboxGroup);
          const isDate = q.field_type === 'date';
          const isTextarea = q.field_type === 'textarea';

          return (
            <div key={q.field_id} className="card p-3 mb-3 bg-white border border-secondary border-opacity-25 rounded-3">
              {/* Section Heading & Question Meta */}
              <div className="d-flex flex-wrap justify-content-between align-items-center gap-2 mb-2">
                <div className="d-flex align-items-center gap-2 flex-wrap">
                  {q.section_heading && (
                    <span className="badge bg-light text-primary border border-primary border-opacity-25">
                      📁 {q.section_heading}
                    </span>
                  )}
                  {q.is_required && (
                    <span className="badge bg-danger bg-opacity-10 text-danger border border-danger border-opacity-25">
                      Required *
                    </span>
                  )}
                  <span className="badge bg-light text-secondary border font-monospace small">
                    id: {q.field_id}
                  </span>
                </div>

                <div className="d-flex align-items-center gap-2">
                  <span className={`badge ${q.confidence >= 0.7 ? 'bg-success' : q.confidence > 0 ? 'bg-info' : 'bg-secondary'}`}>
                    Confidence: {(q.confidence * 100).toFixed(0)}%
                  </span>
                </div>
              </div>

              {/* Complete Question Text */}
              <div className="mb-2">
                <label className="fw-bold text-dark fs-6 d-block mb-1">
                  Question #{idx + 1}: {title}
                </label>
                {q.helper_text && (
                  <p className="text-muted small mb-1 fst-italic">
                    ℹ️ Instructions: {q.helper_text}
                  </p>
                )}
              </div>

              {/* Reason why human review is required */}
              <div className="mb-3 p-2 bg-light rounded small text-secondary">
                <div className="d-flex gap-1">
                  <strong className="text-dark">Reason:</strong>
                  <span>{q.reason}</span>
                </div>
                {q.source_citations && q.source_citations.length > 0 && (
                  <div className="d-flex gap-1 mt-1 text-muted">
                    <strong>Reference:</strong>
                    <span>{q.source_citations.join(', ')}</span>
                  </div>
                )}
              </div>

              {/* Dynamic Input Control according to field type */}
              <div className="mb-3">
                <label className="form-label fw-semibold small text-dark mb-1">
                  Select or Enter Answer:
                </label>

                {isSelect ? (
                  <select
                    className="form-select"
                    value={currentVal}
                    onChange={(e) => handleChange(q.field_id, e.target.value)}
                  >
                    <option value="">-- Choose an option --</option>
                    {q.options?.map((opt, oIdx) => (
                      <option key={oIdx} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                ) : isCheckboxGroup ? (
                  <div className="d-flex flex-column gap-2 mt-1">
                    <span className="text-muted small">Select all applicable options:</span>
                    <div className="d-flex flex-wrap gap-2">
                      {q.options?.map((opt, oIdx) => {
                        const selectedList = currentVal ? currentVal.split(',').map(s => s.trim()) : [];
                        const isChecked = selectedList.includes(opt);
                        const handleToggle = () => {
                          const nextList = isChecked
                            ? selectedList.filter(s => s !== opt)
                            : [...selectedList, opt];
                          handleChange(q.field_id, nextList.join(', '));
                        };
                        return (
                          <label
                            key={oIdx}
                            className={`d-flex align-items-center gap-2 p-2 px-3 rounded border cursor-pointer ${
                              isChecked
                                ? 'bg-primary bg-opacity-10 border-primary text-primary fw-semibold'
                                : 'bg-light bg-opacity-50 text-dark'
                            }`}
                          >
                            <input
                              type="checkbox"
                              name={`cb_${q.field_id}`}
                              value={opt}
                              checked={isChecked}
                              onChange={handleToggle}
                              className="form-check-input mt-0"
                            />
                            <span className="small">{opt}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                ) : isRadio ? (
                  <div className="d-flex flex-column gap-2 mt-1">
                    {q.options?.map((opt, oIdx) => (
                      <label key={oIdx} className="d-flex align-items-center gap-2 p-2 rounded border bg-light bg-opacity-50 cursor-pointer">
                        <input
                          type="radio"
                          name={`radio_${q.field_id}`}
                          value={opt}
                          checked={currentVal === opt}
                          onChange={() => handleChange(q.field_id, opt)}
                          className="form-check-input mt-0"
                        />
                        <span className="small text-dark">{opt}</span>
                      </label>
                    ))}
                  </div>
                ) : isTextarea ? (
                  <textarea
                    rows={3}
                    className="form-control"
                    value={currentVal}
                    onChange={(e) => handleChange(q.field_id, e.target.value)}
                    placeholder="Enter full details"
                  />
                ) : isDate ? (
                  <input
                    type="date"
                    className="form-control"
                    value={currentVal}
                    onChange={(e) => handleChange(q.field_id, e.target.value)}
                  />
                ) : (
                  <input
                    type="text"
                    className="form-control"
                    value={currentVal}
                    onChange={(e) => handleChange(q.field_id, e.target.value)}
                    placeholder="Enter answer"
                  />
                )}
              </div>

              {/* Suggested Answer & Action Buttons */}
              <div className="d-flex justify-content-between align-items-center pt-2 border-top">
                <div>
                  {q.answer && (
                    <button
                      type="button"
                      className="btn btn-sm btn-outline-success d-flex align-items-center gap-1"
                      onClick={() => handleAcceptSuggested(q)}
                    >
                      <span>💡 Use Suggested:</span>
                      <strong>"{q.answer}"</strong>
                    </button>
                  )}
                </div>
                <button
                  type="button"
                  className="btn btn-sm btn-link text-muted text-decoration-none"
                  onClick={() => handleChange(q.field_id, '')}
                >
                  Clear Answer
                </button>
              </div>
            </div>
          );
        })}

        {validationError && (
          <div className="alert alert-danger py-2 px-3 small d-flex align-items-center gap-2 mt-3 mb-0">
            <span>⚠️</span>
            <span>{validationError}</span>
          </div>
        )}

        <div className="d-flex justify-content-end gap-2 mt-4">
          <button type="submit" className="btn btn-primary px-4 py-2 fw-semibold shadow-sm">
            Confirm Answers &amp; Resume Automation →
          </button>
        </div>
      </form>
    </div>
  );
};
