import React, { useState, useEffect } from 'react';

interface Model {
  id: string;
  label: string;
  description: string;
  size_gb: number;
  resolution?: string;
  nsfw: boolean;
  recommended_nsfw?: boolean;
  anime?: boolean;
  downloaded?: boolean;
}

interface ModelSelectorProps {
  models: Model[];
  selectedModelId: string;
  onSelect: (modelId: string) => void;
  contentRating: 'sfw' | 'mature';
  showDownloadStatus?: boolean;
}

type FilterType = 'all' | 'anime' | 'realistic' | 'nsfw' | 'sfw';

/**
 * Model Selector
 *
 * Grid/list of available models with filtering.
 * Shows NSFW badges and download status.
 */
export const ModelSelector: React.FC<ModelSelectorProps> = ({
  models,
  selectedModelId,
  onSelect,
  contentRating,
  showDownloadStatus = true,
}) => {
  const [filter, setFilter] = useState<FilterType>('all');
  const [searchQuery, setSearchQuery] = useState('');

  // Filter models based on content rating and user filters
  const filteredModels = models.filter((model) => {
    // Hide NSFW models in SFW mode
    if (contentRating === 'sfw' && model.nsfw) {
      return false;
    }

    // Apply user filter
    if (filter === 'anime' && !model.anime) return false;
    if (filter === 'nsfw' && !model.nsfw) return false;
    if (filter === 'sfw' && model.nsfw) return false;

    // Apply search
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return (
        model.label.toLowerCase().includes(q) ||
        model.description.toLowerCase().includes(q)
      );
    }

    return true;
  });

  return (
    <div className="model-selector">
      {/* Filters */}
      <div className="filters">
        <input
          type="text"
          className="search-input"
          placeholder="Search models..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />

        <div className="filter-pills">
          {(['all', 'anime', 'nsfw', 'sfw'] as FilterType[]).map((f) => (
            <button
              key={f}
              className={`filter-pill ${filter === f ? 'active' : ''}`}
              onClick={() => setFilter(f)}
              disabled={f === 'nsfw' && contentRating === 'sfw'}
            >
              {f === 'all' && 'All'}
              {f === 'anime' && '\uD83C\uDF38 Anime'}
              {f === 'nsfw' && '\uD83D\uDD1E NSFW'}
              {f === 'sfw' && '\u2713 SFW'}
            </button>
          ))}
        </div>
      </div>

      {/* Model Grid */}
      <div className="model-grid">
        {filteredModels.map((model) => (
          <div
            key={model.id}
            className={`model-card ${selectedModelId === model.id ? 'selected' : ''}`}
            onClick={() => onSelect(model.id)}
          >
            <div className="model-preview">
              <div className="model-icon">
                {model.anime ? '\uD83C\uDF38' : '\uD83D\uDDBC\uFE0F'}
              </div>
            </div>

            <div className="model-info">
              <h4 className="model-name">{model.label}</h4>
              <p className="model-description">{model.description}</p>

              <div className="model-meta">
                <span className="model-size">{model.size_gb} GB</span>
                {model.resolution && (
                  <span className="model-resolution">{model.resolution}</span>
                )}
              </div>

              <div className="model-badges">
                {model.nsfw ? (
                  <span className="badge badge-nsfw">\uD83D\uDD1E NSFW</span>
                ) : (
                  <span className="badge badge-sfw">\u2713 SFW</span>
                )}
                {model.recommended_nsfw && (
                  <span className="badge badge-recommended">\u2B50 Recommended</span>
                )}
                {model.anime && (
                  <span className="badge badge-anime">Anime</span>
                )}
              </div>
            </div>

            {showDownloadStatus && (
              <div className="download-status">
                {model.downloaded ? (
                  <span className="status-ready">\u2713 Ready</span>
                ) : (
                  <button className="download-btn">Download</button>
                )}
              </div>
            )}
          </div>
        ))}

        {filteredModels.length === 0 && (
          <div className="no-results">
            <p>No models match your filters</p>
            {contentRating === 'sfw' && filter === 'nsfw' && (
              <p className="hint">Enable Mature mode to see NSFW models</p>
            )}
          </div>
        )}
      </div>

      <style>{`
        .model-selector {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .filters {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .search-input {
          width: 100%;
          padding: 10px 14px;
          border: 1px solid var(--color-border);
          border-radius: 8px;
          background: var(--color-background);
          color: var(--color-text);
          font-size: 14px;
        }

        .search-input:focus {
          outline: none;
          border-color: var(--color-primary);
        }

        .filter-pills {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
        }

        .filter-pill {
          padding: 6px 14px;
          border: 1px solid var(--color-border);
          border-radius: 20px;
          background: var(--color-surface);
          color: var(--color-text-muted);
          font-size: 13px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .filter-pill:hover:not(:disabled) {
          border-color: var(--color-primary);
          color: var(--color-primary);
        }

        .filter-pill.active {
          background: var(--color-primary);
          border-color: var(--color-primary);
          color: white;
        }

        .filter-pill:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        .model-grid {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .model-card {
          display: flex;
          align-items: flex-start;
          gap: 14px;
          padding: 14px;
          background: var(--color-surface);
          border: 2px solid var(--color-border);
          border-radius: 10px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .model-card:hover {
          border-color: var(--color-primary);
        }

        .model-card.selected {
          border-color: var(--color-primary);
          background: var(--color-primary-light);
        }

        .model-preview {
          width: 60px;
          height: 60px;
          border-radius: 8px;
          background: var(--color-background);
          display: flex;
          align-items: center;
          justify-content: center;
          flex-shrink: 0;
        }

        .model-icon {
          font-size: 28px;
        }

        .model-info {
          flex: 1;
          min-width: 0;
        }

        .model-name {
          margin: 0 0 4px;
          font-size: 14px;
          font-weight: 600;
          color: var(--color-text);
        }

        .model-description {
          margin: 0 0 8px;
          font-size: 12px;
          color: var(--color-text-muted);
          line-height: 1.4;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
        }

        .model-meta {
          display: flex;
          gap: 12px;
          margin-bottom: 8px;
          font-size: 11px;
          color: var(--color-text-light);
        }

        .model-badges {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }

        .badge {
          padding: 3px 8px;
          border-radius: 4px;
          font-size: 11px;
          font-weight: 500;
        }

        .badge-nsfw {
          background: linear-gradient(135deg, #8B5CF6, #F59E0B);
          color: white;
        }

        .badge-sfw {
          background: #D1FAE5;
          color: #065F46;
        }

        .badge-recommended {
          background: #FEF3C7;
          color: #92400E;
        }

        .badge-anime {
          background: #FCE7F3;
          color: #9D174D;
        }

        .download-status {
          flex-shrink: 0;
        }

        .status-ready {
          color: #10B981;
          font-size: 12px;
          font-weight: 500;
        }

        .download-btn {
          padding: 6px 12px;
          background: var(--color-primary);
          color: white;
          border: none;
          border-radius: 6px;
          font-size: 12px;
          cursor: pointer;
        }

        .download-btn:hover {
          background: var(--color-primary-hover);
        }

        .no-results {
          text-align: center;
          padding: 40px 20px;
          color: var(--color-text-muted);
        }

        .no-results .hint {
          font-size: 13px;
          color: var(--color-text-light);
          margin-top: 8px;
        }
      `}</style>
    </div>
  );
};
