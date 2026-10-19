import React, { useState } from 'react';

interface Props {
  onStart: (url: string) => void;
  isLoading: boolean;
}

export const UrlInputCard: React.FC<Props> = ({ onStart, isLoading }) => {
  const [url, setUrl] = useState('http://localhost:8001/mock_form.html');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (url.trim()) {
      onStart(url.trim());
    }
  };

  return (
    <div className="card card-custom p-4 border-left-primary">
      <h4 className="mb-3 text-primary">Job Application URL</h4>
      <form onSubmit={handleSubmit}>
        <div className="input-group mb-3">
          <input
            type="text"
            className="form-control form-control-lg"
            placeholder="Paste target job application URL (e.g. https://company.com/apply)"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={isLoading}
          />
          <button
            className="btn btn-primary btn-lg px-4"
            type="submit"
            disabled={isLoading || !url.trim()}
          >
            {isLoading ? (
              <>
                <span className="spinner-border spinner-border-sm me-2" role="status"></span>
                Processing...
              </>
            ) : (
              'Start Application'
            )}
          </button>
        </div>
        <div className="form-text text-muted">
          Generic automation engine. Works with startups, MNCs, single-page, and multi-page application forms.
        </div>
      </form>
    </div>
  );
};
