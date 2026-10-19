import React from 'react';

interface Props {
  status: string;
  loginRequired: boolean;
}

export const ProgressTimeline: React.FC<Props> = ({ status, loginRequired }) => {
  const steps = [
    { key: 'CREATED', label: 'Application Session Initialized' },
    { key: 'LOGIN', label: 'Authentication Check', isLogin: true },
    { key: 'RUNNING', label: 'Page Analysis & Field Extraction' },
    { key: 'MAPPING', label: 'Profile Retrieval & RAG Matching' },
    { key: 'WAITING_FOR_USER', label: 'Human Review & HITL Verification' },
    { key: 'READY_FOR_REVIEW', label: 'Application Ready for Review' },
    { key: 'SUBMITTED', label: 'Final Submission Approved & Submitted' }
  ];

  const getStepStatus = (stepKey: string) => {
    if (status === 'SUBMITTED') return 'completed';
    if (stepKey === 'CREATED' && status !== 'CREATED') return 'completed';
    if (stepKey === 'LOGIN') {
      if (status === 'LOGIN_REQUIRED' || loginRequired) return 'paused';
      if (status !== 'CREATED') return 'completed';
    }
    if (status === 'READY_FOR_REVIEW' && (stepKey === 'CREATED' || stepKey === 'LOGIN' || stepKey === 'RUNNING' || stepKey === 'MAPPING' || stepKey === 'WAITING_FOR_USER')) return 'completed';
    if (status === 'WAITING_FOR_USER' && (stepKey === 'CREATED' || stepKey === 'LOGIN' || stepKey === 'RUNNING' || stepKey === 'MAPPING')) return 'completed';
    if (status === stepKey) return 'active';
    return 'pending';
  };

  return (
    <div className="card card-custom p-4">
      <h5 className="card-title mb-4">Application Workflow Progress</h5>
      <div className="timeline">
        {steps.map((s, idx) => {
          const st = getStepStatus(s.key);
          let badgeClass = 'status-pending';
          let symbol: string | number = idx + 1;

          if (st === 'completed') {
            badgeClass = 'status-completed';
            symbol = '✓';
          } else if (st === 'active') {
            badgeClass = 'status-active';
            symbol = '→';
          } else if (st === 'paused') {
            badgeClass = 'status-paused';
            symbol = '!';
          }

          return (
            <div key={s.key} className="timeline-step">
              <div className={`timeline-icon ${badgeClass}`}>{symbol}</div>
              <div>
                <div className="fw-semibold">{s.label}</div>
                {st === 'paused' && (
                  <div className="text-warning small fw-bold">Manual User Action Required (Authentication Barrier)</div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
