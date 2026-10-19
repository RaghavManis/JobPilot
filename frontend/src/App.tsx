import React, { useState, useEffect, useRef } from 'react';
import { UrlInputCard } from './components/UrlInputCard';
import { ProgressTimeline } from './components/ProgressTimeline';
import { HumanInteractionModal } from './components/HumanInteractionModal';
import { FinalReviewPanel } from './components/FinalReviewPanel';
import { api, ApplicationState } from './api/client';

export const App: React.FC = () => {
  const [session, setSession] = useState<any>(null);
  const [workflowState, setWorkflowState] = useState<ApplicationState | null>(null);
  const [loading, setLoading] = useState(false);
  const [liveSubStatus, setLiveSubStatus] = useState<string>('');
  const [logs, setLogs] = useState<string[]>([]);
  const eventSourceRef = useRef<EventSource | null>(null);
  const logContainerRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll log console to newest entry at bottom
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs]);

  const addLog = (msg: string) => {
    setLogs(prev => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);
  };

  // Close event stream when component unmounts
  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  const setupEventStream = (sessionId: string) => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const es = api.createEventSource(sessionId);
    eventSourceRef.current = es;

    es.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'log') {
          const time = data.timestamp ? new Date(data.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();
          const prefix = data.level === 'warning' ? '⚠️ ' : data.level === 'error' ? '❌ ' : data.action ? '👉 ' : '';
          setLogs(prev => [...prev, `[${time}] ${prefix}${data.message}`]);
        } else if (data.type === 'status') {
          setLiveSubStatus(data.detail || data.status);
          if (data.status) {
            setWorkflowState(prev => prev ? ({ ...prev, status: data.status }) : null);
          }
        }
      } catch (err) {
        // Heartbeat or ping
      }
    };

    es.onerror = () => {
      // Reconnection handled automatically by browser EventSource
    };
  };

  const handleStartApplication = async (url: string) => {
    setLoading(true);
    setLogs([]);
    setLiveSubStatus('Initializing visible browser...');
    try {
      addLog(`Creating session for target URL: ${url}`);
      const newSession = await api.createSession(url);
      setSession(newSession);

      // Start live real-time event streaming
      setupEventStream(newSession.id);
      addLog(`Session ${newSession.id} created. Launching visible Chromium browser...`);

      // Run workflow execution: opens visible browser and executes automation
      const state1 = await api.runStep(newSession.id);
      setWorkflowState(state1);

    } catch (err: any) {
      addLog(`Error starting application: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleResumeWorkflow = async (answers: Record<string, string>) => {
    if (!session) return;
    console.log("App: handleResumeWorkflow called with answers:", answers);
    setLoading(true);
    try {
      addLog('Human review confirmed. Submitting answers and resuming workflow in visible browser...');
      const nextState = await api.submitHumanReview(session.id, answers);
      console.log("App: submitHumanReview returned state:", nextState);
      setWorkflowState(nextState);
      addLog(`Workflow resumed. Current status: ${nextState.status}`);
    } catch (err: any) {
      console.error("App: submitHumanReview error:", err);
      addLog(`Error resuming workflow: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleApproveSubmission = async () => {
    if (!session) return;
    setLoading(true);
    try {
      addLog('Explicit human approval received. Executing final submission in visible browser...');
      const finalState = await api.approveSubmission(session.id);
      setWorkflowState(finalState);
      if (finalState.status === 'SUBMITTED') {
        addLog(`🎉 Application successfully SUBMITTED and verified in browser!`);
      } else if (finalState.status === 'WAITING_FOR_USER' || (finalState.status as string) === 'NEEDS_INPUT') {
        addLog(`⚠️ Action required before submission: ${finalState.error_message || 'Please complete required fields or verification in the browser.'}`);
      } else if ((finalState.status as string) === 'BLOCKED') {
        addLog(`🚫 Submission blocked: ${finalState.error_message || 'Please inspect browser window.'}`);
      } else {
        addLog(`Submission status: ${finalState.status}. ${finalState.error_message || ''}`);
      }
    } catch (err: any) {
      addLog(`Submission error: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handlePause = async () => {
    if (!session) return;
    try {
      addLog('Pausing automation by user request...');
      const paused = await api.pause(session.id);
      setWorkflowState(paused);
    } catch (err: any) {
      addLog(`Failed to pause: ${err.message}`);
    }
  };

  const handleResumeFromPause = async () => {
    if (!session) return;
    setLoading(true);
    try {
      addLog('Resuming automation from pause...');
      const resumed = await api.resume(session.id);
      setWorkflowState(resumed);
    } catch (err: any) {
      addLog(`Failed to resume: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleStop = async () => {
    if (!session) return;
    try {
      addLog('Stopping automation and closing browser...');
      await api.stop(session.id);
      setWorkflowState(prev => prev ? ({ ...prev, status: 'STOPPED' }) : null);
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    } catch (err: any) {
      addLog(`Failed to stop: ${err.message}`);
    }
  };

  const [focusingBrowser, setFocusingBrowser] = useState(false);
  const [focusFeedback, setFocusFeedback] = useState<{ type: 'success' | 'error' | 'info'; message: string } | null>(null);

  const handleFocusBrowser = async () => {
    if (!session || !session.id) {
      setFocusFeedback({
        type: 'info',
        message: 'No active browser session. Start an application session first.'
      });
      setTimeout(() => setFocusFeedback(null), 4000);
      return;
    }

    if (focusingBrowser) return;

    setFocusingBrowser(true);
    setFocusFeedback(null);

    try {
      const result = await api.focusBrowser(session.id);
      addLog(`Brought visible browser window to front. (${result.detail || result.message})`);
      setFocusFeedback({
        type: 'success',
        message: '✓ Browser window brought to front!'
      });
      setTimeout(() => setFocusFeedback(null), 3500);
    } catch (err: any) {
      const errorMsg = err.message || 'Could not focus browser.';
      addLog(`Could not focus browser: ${errorMsg}`);
      setFocusFeedback({
        type: 'error',
        message: errorMsg
      });
      setTimeout(() => setFocusFeedback(null), 5000);
    } finally {
      setFocusingBrowser(false);
    }
  };

  const [uploadingPhoto, setUploadingPhoto] = useState(false);
  const [photoFeedback, setPhotoFeedback] = useState<string | null>(null);

  const handlePhotoUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingPhoto(true);
    setPhotoFeedback(null);
    try {
      const res = await api.uploadPhoto(file, session?.user_id || 'user_default');
      setPhotoFeedback(`✅ Stored photo: ${res.filename}`);
      addLog(`Profile photo uploaded successfully (${res.filename}). Ready for standard photo form uploads.`);
    } catch (err: any) {
      setPhotoFeedback(`❌ Upload failed: ${err.message}`);
      addLog(`Profile photo upload error: ${err.message}`);
    } finally {
      setUploadingPhoto(false);
    }
  };

  const isSessionActive = Boolean(session && workflowState && workflowState.status !== 'SUBMITTED' && workflowState.status !== 'STOPPED');

  return (
    <div>
      {/* Top Navbar */}
      <nav className="navbar navbar-dark bg-gradient-header py-3">
        <div className="container">
          <a className="navbar-brand d-flex align-items-center gap-2" href="#">
            <span className="fs-3">✈️</span>
            <div>
              <span className="fw-bold">JobPilot</span>
              <span className="text-secondary small ms-2">Live Browser Automation</span>
            </div>
          </a>
          <div className="d-flex align-items-center gap-3">
            {isSessionActive && (
              <span className="badge bg-dark border border-secondary d-flex align-items-center gap-2 py-2 px-3">
                <span className="live-pulse"></span>
                <span>Visible Browser Active</span>
              </span>
            )}
            <span className="badge bg-primary px-3 py-2">Universal Agent</span>
          </div>
        </div>
      </nav>

      {/* Main Container */}
      <div className="container my-4">
        {/* Live Browser Controls Banner */}
        {session && workflowState && (
          <div className="card card-custom p-3 mb-4 border-0 shadow-sm bg-white">
            <div className="d-flex flex-wrap justify-content-between align-items-center gap-3">
              <div className="d-flex align-items-center gap-3">
                <span className="fs-3">🖥️</span>
                <div>
                  <div className="d-flex align-items-center gap-2">
                    <span className="fw-bold text-dark">Visible Browser Window</span>
                    {workflowState.status === 'RUNNING' && (
                      <span className="badge bg-success-subtle text-success border border-success-subtle px-2 py-1 small">
                        Automating Live
                      </span>
                    )}
                    {workflowState.status === 'PAUSED' && (
                      <span className="badge bg-warning-subtle text-warning border border-warning-subtle px-2 py-1 small">
                        Paused
                      </span>
                    )}
                    {workflowState.status === 'WAITING_FOR_USER' && (
                      <span className="badge bg-info-subtle text-info border border-info-subtle px-2 py-1 small">
                        Awaiting Human Input
                      </span>
                    )}
                    {workflowState.status === 'STOPPED' && (
                      <span className="badge bg-secondary px-2 py-1 small">Stopped</span>
                    )}
                  </div>
                  <div className="text-muted small">
                    {liveSubStatus || `Status: ${workflowState.status}`}
                  </div>
                </div>
              </div>

              {/* Action Controls */}
              <div className="d-flex gap-2 align-items-center flex-wrap">
                <div className="position-relative d-inline-block">
                  <button
                    type="button"
                    className={`btn btn-sm ${
                      focusFeedback?.type === 'success'
                        ? 'btn-success'
                        : focusFeedback?.type === 'error'
                        ? 'btn-outline-danger'
                        : 'btn-outline-primary'
                    } fw-semibold d-flex align-items-center gap-2`}
                    onClick={handleFocusBrowser}
                    disabled={focusingBrowser}
                    title="Bring the visible browser window to the front on your desktop"
                  >
                    {focusingBrowser ? (
                      <>
                        <span className="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
                        <span>Bringing browser to front...</span>
                      </>
                    ) : focusFeedback?.type === 'success' ? (
                      <>
                        <span>✓</span>
                        <span>Browser in Front!</span>
                      </>
                    ) : (
                      <>
                        <span>🖥️</span>
                        <span>Bring Window to Front</span>
                      </>
                    )}
                  </button>
                  {focusFeedback && focusFeedback.type !== 'success' && (
                    <div
                      className={`alert ${
                        focusFeedback.type === 'error' ? 'alert-danger' : 'alert-info'
                      } position-absolute shadow-sm p-2 small mt-1 end-0 text-nowrap`}
                      style={{ zIndex: 1060, fontSize: '0.8rem', maxWidth: '320px', whiteSpace: 'normal' }}
                    >
                      {focusFeedback.message}
                    </div>
                  )}
                </div>

                {workflowState.status === 'RUNNING' && (
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-warning fw-semibold"
                    onClick={handlePause}
                  >
                    ⏸️ Pause
                  </button>
                )}

                {workflowState.status === 'PAUSED' && (
                  <button
                    type="button"
                    className="btn btn-sm btn-success fw-semibold"
                    onClick={handleResumeFromPause}
                    disabled={loading}
                  >
                    ▶️ Resume Automation
                  </button>
                )}

                {workflowState.status !== 'SUBMITTED' && workflowState.status !== 'STOPPED' && (
                  <button
                    type="button"
                    className="btn btn-sm btn-outline-danger fw-semibold"
                    onClick={handleStop}
                  >
                    ⏹️ Stop &amp; Close Browser
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        <div className="row">
          <div className="col-lg-8">
            <UrlInputCard onStart={handleStartApplication} isLoading={loading} />

            {/* Automation Paused Notice */}
            {workflowState?.status === 'PAUSED' && (
              <div className="alert alert-warning p-4 border-left-warning mb-4">
                <h5>⏸️ Automation Paused</h5>
                <p className="mb-3">
                  The visible browser window remains open on your desktop. You can inspect the page, fill details directly, or resolve any prompts, then click <strong>Resume Automation</strong>.
                </p>
                <button
                  className="btn btn-warning fw-bold px-4"
                  onClick={handleResumeFromPause}
                  disabled={loading}
                >
                  ▶️ Resume Automation
                </button>
              </div>
            )}

            {/* Authentication Barrier Card */}
            {(workflowState?.login_required || workflowState?.status === 'LOGIN_REQUIRED') && (
              <div className="card card-custom p-4 border-left-warning mb-4 shadow-sm">
                <div className="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-3">
                  <div className="d-flex align-items-center gap-2">
                    <span className="fs-3">🔐</span>
                    <div>
                      <h4 className="m-0 fw-bold text-dark">Portal Authentication Required</h4>
                      <span className="badge bg-warning text-dark mt-1">
                        {workflowState.auth_category === 'LOGIN_OR_REGISTER'
                          ? 'Sign-in or Account Registration'
                          : workflowState.auth_category === 'REGISTRATION'
                          ? 'New Account Registration'
                          : workflowState.auth_category === 'OTP_VERIFICATION'
                          ? 'Two-Step Verification / OTP'
                          : workflowState.auth_category === 'CAPTCHA'
                          ? 'Security Verification'
                          : 'Candidate Login Required'}
                      </span>
                    </div>
                  </div>
                  <span className="badge bg-light text-secondary border px-3 py-2 small">
                    Security Privacy Gate
                  </span>
                </div>

                <p className="text-secondary mb-3">
                  {workflowState.auth_details ||
                    'This job portal requires authentication or account creation before the job application form can be accessed.'}
                </p>

                <div className="row g-3 mb-4">
                  <div className="col-md-6">
                    <div className="p-3 bg-light rounded border h-100">
                      <div className="fw-bold text-dark mb-1">Option A: Existing Account</div>
                      <p className="small text-secondary mb-0">
                        If you already have credentials on this portal, bring the browser to front and sign in with your email and password.
                      </p>
                    </div>
                  </div>
                  <div className="col-md-6">
                    <div className="p-3 bg-light rounded border h-100">
                      <div className="fw-bold text-dark mb-1">Option B: New Applicant Registration</div>
                      <p className="small text-secondary mb-0">
                        If you are applying to this company for the first time, click <strong>Create Account / Register</strong> in the browser to set up your profile.
                      </p>
                    </div>
                  </div>
                </div>

                <div className="p-3 bg-warning-subtle border border-warning-subtle rounded small mb-4 text-dark">
                  🛡️ <strong>Privacy Protection:</strong> JobPilot never asks for, records, or stores your passwords in the dashboard. You complete all credentials directly in the visible Chromium browser.
                </div>

                <div className="d-flex gap-3 align-items-center flex-wrap">
                  <button
                    type="button"
                    className="btn btn-outline-primary fw-semibold d-flex align-items-center gap-2"
                    onClick={handleFocusBrowser}
                    disabled={focusingBrowser}
                  >
                    <span>🖥️</span>
                    <span>Bring Browser Window to Front</span>
                  </button>

                  <button
                    type="button"
                    className="btn btn-warning fw-bold px-4 d-flex align-items-center gap-2"
                    disabled={loading}
                    onClick={async () => {
                      if (!session) return;
                      setLoading(true);
                      addLog('Resuming workflow after authentication. Re-analyzing application page...');
                      try {
                        let nextState = await api.completeLogin(session.id);
                        setWorkflowState(nextState);
                        addLog(`Workflow updated. Current status: ${nextState.status}`);
                        if (nextState.status === 'RUNNING') {
                          nextState = await api.runStep(session.id);
                          setWorkflowState(nextState);
                          addLog(`Workflow advanced. Current status: ${nextState.status}`);
                        }
                      } catch (e: any) {
                        addLog(`Error resuming after authentication: ${e.message}`);
                      } finally {
                        setLoading(false);
                      }
                    }}
                  >
                    {loading ? (
                      <>
                        <span className="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>
                        <span>Verifying & Resuming...</span>
                      </>
                    ) : (
                      <>
                        <span>✅</span>
                        <span>I Have Completed Authentication (Resume Agent)</span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}

            {/* Live Camera / Selfie Verification Barrier Card */}
            {workflowState?.status === 'CAMERA_VERIFICATION_REQUIRED' && (
              <div className="card card-custom p-4 border-left-warning mb-4 shadow-sm">
                <div className="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-3">
                  <div className="d-flex align-items-center gap-2">
                    <span className="fs-3">📷</span>
                    <div>
                      <h4 className="m-0 fw-bold text-dark">Live Selfie / Camera Verification Required</h4>
                      <span className="badge bg-warning text-dark mt-1">Real-time Identity Verification</span>
                    </div>
                  </div>
                  <span className="badge bg-light text-secondary border px-3 py-2 small">
                    Human Verification Required
                  </span>
                </div>

                <p className="text-secondary mb-3">
                  This portal requires real-time identity verification (such as capturing a live selfie, scanning photo ID, or granting webcam permissions). 
                  JobPilot automatically pauses here so you can personally complete the verification in the visible browser window without risk.
                </p>

                <div className="p-3 bg-light rounded border mb-4">
                  <div className="fw-bold text-dark mb-1">Instructions:</div>
                  <ol className="small text-secondary mb-0 ps-3">
                    <li>Click <strong>Bring Browser Window to Front</strong> below to view the camera prompt.</li>
                    <li>Allow camera access if requested, position your face in the guide, and capture the photo.</li>
                    <li>Once completed or accepted on the portal, click <strong>Resume Automation</strong>.</li>
                  </ol>
                </div>

                <div className="d-flex gap-3 align-items-center flex-wrap">
                  <button
                    type="button"
                    className="btn btn-outline-primary fw-semibold d-flex align-items-center gap-2"
                    onClick={handleFocusBrowser}
                    disabled={focusingBrowser}
                  >
                    <span>🖥️</span>
                    <span>Bring Browser Window to Front</span>
                  </button>

                  <button
                    type="button"
                    className="btn btn-warning fw-bold px-4"
                    disabled={loading}
                    onClick={handleResumeFromPause}
                  >
                    {loading ? (
                      <>
                        <span className="spinner-border spinner-border-sm me-2" role="status"></span>
                        <span>Resuming...</span>
                      </>
                    ) : (
                      '✅ I Have Completed Camera Verification (Resume)'
                    )}
                  </button>
                </div>
              </div>
            )}

            {/* Human Interaction Questions */}
            {workflowState?.status === 'WAITING_FOR_USER' &&
              (workflowState.human_review_queue || []).length > 0 && (
                <HumanInteractionModal
                  questions={workflowState.human_review_queue || []}
                  onComplete={handleResumeWorkflow}
                />
              )}

            {/* Verification / OTP / Submission Barrier Card */}
            {Boolean(workflowState && ['WAITING_FOR_USER', 'NEEDS_INPUT', 'BLOCKED'].includes(workflowState.status) &&
              (workflowState.human_review_queue || []).length === 0) && workflowState && (
                <div className="card card-custom p-4 border-left-warning mb-4 shadow-sm">
                  <div className="d-flex align-items-center justify-content-between flex-wrap gap-2 mb-3">
                    <div className="d-flex align-items-center gap-2">
                      <span className="fs-3">
                        {workflowState.auth_category === 'OTP_VERIFICATION' ? '🔐' : '⚠️'}
                      </span>
                      <div>
                        <h4 className="m-0 fw-bold text-dark">
                          {workflowState.auth_category === 'OTP_VERIFICATION'
                            ? 'One-Time Passcode (OTP) Verification Required'
                            : (workflowState.validation_errors || []).length > 0
                            ? 'Form Validation Issue Detected'
                            : 'Additional Browser Verification Required'}
                        </h4>
                        <span className="badge bg-warning text-dark mt-1">
                          {workflowState.auth_category === 'OTP_VERIFICATION'
                            ? 'SMS / Email OTP Verification'
                            : 'Action Required in Browser'}
                        </span>
                      </div>
                    </div>
                    <span className="badge bg-light text-secondary border px-3 py-2 small">
                      Human in the Loop
                    </span>
                  </div>

                  <p className="text-secondary mb-3">
                    {workflowState.auth_category === 'OTP_VERIFICATION'
                      ? 'The job portal is requesting a one-time passcode (OTP) or security verification code to finalize your application. Please check your phone or email, enter the code in the visible browser window, and click below to complete submission.'
                      : workflowState.error_message ||
                        'The browser page requires your direct confirmation or attention to complete this step. Please switch to the visible browser window, complete any required fields, and resume.'}
                  </p>

                  {(workflowState.validation_errors || []).length > 0 && (
                    <div className="p-3 bg-danger-subtle text-danger rounded border border-danger-subtle mb-3 small">
                      <strong>Reported Page Validation Issues:</strong>
                      <ul className="mb-0 mt-1 ps-3">
                        {workflowState.validation_errors.map((err, i) => (
                          <li key={i}>{err}</li>
                        ))}
                      </ul>
                    </div>
                  )}

                  <div className="p-3 bg-light rounded border mb-4">
                    <div className="fw-bold text-dark mb-1">Instructions:</div>
                    <ol className="small text-secondary mb-0 ps-3">
                      <li>Click <strong>Bring Browser Window to Front</strong> below to inspect the page.</li>
                      <li>Complete the prompt, enter the OTP, or resolve highlighted validation errors in the portal.</li>
                      <li>Click <strong>I Have Completed Verification (Submit / Resume)</strong> to verify and finish.</li>
                    </ol>
                  </div>

                  <div className="d-flex gap-3 align-items-center flex-wrap">
                    <button
                      type="button"
                      className="btn btn-outline-primary fw-semibold d-flex align-items-center gap-2"
                      onClick={handleFocusBrowser}
                      disabled={focusingBrowser}
                    >
                      <span>🖥️</span>
                      <span>Bring Browser Window to Front</span>
                    </button>

                    <button
                      type="button"
                      className="btn btn-success fw-bold px-4"
                      disabled={loading}
                      onClick={workflowState.submission_approved ? handleApproveSubmission : handleResumeFromPause}
                    >
                      {loading ? (
                        <>
                          <span className="spinner-border spinner-border-sm me-2" role="status"></span>
                          <span>Verifying & Submitting...</span>
                        </>
                      ) : (
                        '✅ I Have Completed Verification (Submit / Resume)'
                      )}
                    </button>
                  </div>
                </div>
              )}

            {/* Error / Failure Panel */}
            {workflowState?.status === 'FAILED' && (
              <div className="card card-custom p-4 border-left-danger mb-4 shadow-sm">
                <div className="d-flex align-items-center mb-3">
                  <div className="rounded-circle bg-danger-subtle p-2 text-danger me-3 fs-3">
                    ⚠️
                  </div>
                  <div>
                    <h5 className="text-danger m-0 fw-bold">Automation Halted</h5>
                    <div className="text-muted small">The application encountered an issue or requires manual assistance.</div>
                  </div>
                </div>
                <div className="alert alert-danger py-2 px-3 small font-monospace mb-3">
                  {workflowState.error_message || 'Application automation halted unexpectedly. Check the activity stream for details.'}
                </div>
                <div className="d-flex gap-2">
                  <button
                    className="btn btn-outline-primary btn-sm"
                    onClick={async () => {
                      if (session) {
                        setLoading(true);
                        try {
                          addLog('Retrying workflow execution...');
                          const nextState = await api.resume(session.id);
                          setWorkflowState(nextState);
                        } catch (err: any) {
                          addLog(`Failed to resume: ${err.message}`);
                        } finally {
                          setLoading(false);
                        }
                      }
                    }}
                    disabled={loading}
                  >
                    🔄 Retry / Resume
                  </button>
                  <button className="btn btn-outline-secondary btn-sm" onClick={() => window.location.reload()}>
                    Start Over
                  </button>
                </div>
              </div>
            )}

            {/* Final Review & Submission Panel */}
            {workflowState?.status === 'READY_FOR_REVIEW' && (
              <FinalReviewPanel
                state={workflowState}
                onApproveAndSubmit={handleApproveSubmission}
                isLoading={loading}
              />
            )}

            {/* Submission Complete Success */}
            {workflowState?.status === 'SUBMITTED' && (
              <div className="card card-custom p-5 border-left-success text-center">
                <h2 className="text-success mb-3">🎉 Application Submitted Successfully!</h2>
                <p className="lead text-secondary">
                  JobPilot has completed and submitted your application for target URL:
                </p>
                <div className="p-3 bg-light rounded text-break font-monospace small my-3">
                  {workflowState.target_url}
                </div>
                <div>
                  <button className="btn btn-primary" onClick={() => window.location.reload()}>
                    Apply for Another Job
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Sidebar */}
          <div className="col-lg-4">
            <ProgressTimeline
              status={workflowState?.status || 'CREATED'}
              loginRequired={workflowState?.login_required || false}
            />

            {/* Live Real-time Activity Log */}
            <div className="card card-custom p-4 mt-4">
              <div className="d-flex justify-content-between align-items-center mb-3">
                <h6 className="card-title m-0 fw-bold">Live Activity Stream</h6>
                {isSessionActive && (
                  <span className="badge bg-success-subtle text-success small">Streaming</span>
                )}
              </div>
              <div
                ref={logContainerRef}
                className="bg-dark text-light p-3 rounded font-monospace small"
                style={{ height: '320px', overflowY: 'auto' }}
              >
                {logs.length === 0 ? (
                  <div className="text-muted">Awaiting application start...</div>
                ) : (
                  logs.map((log, i) => (
                    <div
                      key={i}
                      className="mb-1"
                      style={{
                        wordBreak: 'break-word',
                        color: log.includes('❌') ? '#f87171' : log.includes('⚠️') ? '#fde047' : log.includes('👉') ? '#60a5fa' : '#f1f5f9'
                      }}
                    >
                      {log}
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Live Browser Visual Highlighting Legend */}
            <div className="card card-custom p-3 mt-4 border-0 bg-light shadow-sm">
              <div className="d-flex align-items-center justify-content-between mb-2">
                <span className="fw-bold small text-dark d-flex align-items-center gap-1">
                  <span>🎨</span> Browser Field Highlighting Legend
                </span>
                <span className="badge bg-secondary-subtle text-secondary small">Playwright Live</span>
              </div>
              <p className="text-muted small mb-2" style={{ fontSize: '11px' }}>
                When watching automation in the visible browser window, elements are highlighted dynamically:
              </p>
              <div className="d-flex flex-column gap-2 small">
                <div className="d-flex align-items-center gap-2">
                  <span style={{ display: 'inline-block', width: '13px', height: '13px', backgroundColor: '#10b981', borderRadius: '3px', flexShrink: 0 }}></span>
                  <span className="text-dark" style={{ fontSize: '12px' }}>
                    <strong>Emerald Green:</strong> Field filled, checked, or verified successfully ✓
                  </span>
                </div>
                <div className="d-flex align-items-center gap-2">
                  <span style={{ display: 'inline-block', width: '13px', height: '13px', backgroundColor: '#8b5cf6', borderRadius: '3px', flexShrink: 0 }}></span>
                  <span className="text-dark" style={{ fontSize: '12px' }}>
                    <strong>Purple:</strong> Dropdown option selection in progress
                  </span>
                </div>
                <div className="d-flex align-items-center gap-2">
                  <span style={{ display: 'inline-block', width: '13px', height: '13px', backgroundColor: '#2563eb', borderRadius: '3px', flexShrink: 0 }}></span>
                  <span className="text-dark" style={{ fontSize: '12px' }}>
                    <strong>Blue:</strong> Text input or textarea human-like typing
                  </span>
                </div>
                <div className="d-flex align-items-center gap-2">
                  <span style={{ display: 'inline-block', width: '13px', height: '13px', backgroundColor: '#06b6d4', borderRadius: '3px', flexShrink: 0 }}></span>
                  <span className="text-dark" style={{ fontSize: '12px' }}>
                    <strong>Cyan:</strong> Checkbox or radio button toggle
                  </span>
                </div>
                <div className="d-flex align-items-center gap-2">
                  <span style={{ display: 'inline-block', width: '13px', height: '13px', backgroundColor: '#ec4899', borderRadius: '3px', flexShrink: 0 }}></span>
                  <span className="text-dark" style={{ fontSize: '12px' }}>
                    <strong>Pink:</strong> Document or profile photo upload
                  </span>
                </div>
                <div className="d-flex align-items-center gap-2">
                  <span style={{ display: 'inline-block', width: '13px', height: '13px', backgroundColor: '#f59e0b', borderRadius: '3px', flexShrink: 0 }}></span>
                  <span className="text-dark" style={{ fontSize: '12px' }}>
                    <strong>Amber:</strong> Button click or navigation trigger
                  </span>
                </div>
              </div>
            </div>

            {/* Profile Photograph Storage Card */}
            <div className="card card-custom p-3 mt-4 border-0 bg-white shadow-sm">
              <div className="d-flex align-items-center justify-content-between mb-2">
                <span className="fw-bold small text-dark d-flex align-items-center gap-1">
                  <span>📸</span> Profile Photograph
                </span>
                <span className="badge bg-light text-secondary border small">Auto-Upload</span>
              </div>
              <p className="text-muted small mb-2" style={{ fontSize: '11px' }}>
                Upload a standard profile photo. When an application portal requests an applicant picture, JobPilot automatically uploads it.
              </p>
              <div className="d-flex flex-column gap-2">
                <input
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  className="form-control form-control-sm"
                  onChange={handlePhotoUpload}
                  disabled={uploadingPhoto}
                />
                {uploadingPhoto && (
                  <div className="d-flex align-items-center gap-2 small text-primary">
                    <span className="spinner-border spinner-border-sm" role="status"></span>
                    <span>Saving photograph...</span>
                  </div>
                )}
                {photoFeedback && (
                  <div className="small p-2 bg-light rounded text-dark" style={{ fontSize: '12px' }}>
                    {photoFeedback}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
