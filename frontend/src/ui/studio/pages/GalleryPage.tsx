import React, { useState, useMemo } from "react";
import { useStudioStore } from "../stores/studioStore";

type FilterType = "all" | "favorites" | "sfw" | "mature";
type SortType = "newest" | "oldest";

/**
 * Gallery Page
 *
 * Displays all generated images with filtering and management.
 */
export const GalleryPage: React.FC = () => {
  const {
    generatedImages,
    selectedImageId,
    setSelectedImageId,
    removeGeneratedImage,
    toggleFavorite,
    clearGallery,
    contentRating,
  } = useStudioStore();

  const [filter, setFilter] = useState<FilterType>("all");
  const [sort, setSort] = useState<SortType>("newest");
  const [searchQuery, setSearchQuery] = useState("");

  // Filter and sort images
  const filteredImages = useMemo(() => {
    let result = [...generatedImages];

    // Apply filter
    switch (filter) {
      case "favorites":
        result = result.filter((img) => img.favorite);
        break;
      case "sfw":
        result = result.filter((img) => img.contentRating === "sfw");
        break;
      case "mature":
        result = result.filter((img) => img.contentRating === "mature");
        break;
    }

    // Apply search
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      result = result.filter(
        (img) =>
          img.prompt.toLowerCase().includes(q) ||
          img.modelId.toLowerCase().includes(q)
      );
    }

    // Apply sort
    if (sort === "oldest") {
      result.reverse();
    }

    return result;
  }, [generatedImages, filter, sort, searchQuery]);

  const selectedImage = generatedImages.find(
    (img) => img.id === selectedImageId
  );

  const handleDownload = (imageUrl: string, filename: string) => {
    const link = document.createElement("a");
    link.href = imageUrl;
    link.download = filename;
    link.click();
  };

  const handleCopyPrompt = (prompt: string) => {
    navigator.clipboard.writeText(prompt);
  };

  return (
    <div className="gallery-page">
      {/* Header */}
      <div className="gallery-header">
        <h2>Gallery</h2>
        <span className="image-count">{generatedImages.length} images</span>
      </div>

      {/* Filters */}
      <div className="gallery-filters">
        <input
          type="text"
          className="search-input"
          placeholder="Search by prompt..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
        />

        <div className="filter-group">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value as FilterType)}
          >
            <option value="all">All Images</option>
            <option value="favorites">Favorites</option>
            <option value="sfw">SFW Only</option>
            {contentRating === "mature" && (
              <option value="mature">Mature Only</option>
            )}
          </select>

          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortType)}
          >
            <option value="newest">Newest First</option>
            <option value="oldest">Oldest First</option>
          </select>

          {generatedImages.length > 0 && (
            <button className="clear-btn" onClick={clearGallery}>
              Clear All
            </button>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className="gallery-content">
        {/* Grid */}
        <div className="gallery-grid">
          {filteredImages.map((image) => (
            <div
              key={image.id}
              className={`gallery-item ${
                selectedImageId === image.id ? "selected" : ""
              }`}
              onClick={() => setSelectedImageId(image.id)}
            >
              <div className="image-wrapper">
                <img src={image.url} alt={image.prompt.slice(0, 50)} />
                <div className="image-overlay">
                  <button
                    className={`fav-btn ${image.favorite ? "active" : ""}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleFavorite(image.id);
                    }}
                  >
                    {image.favorite ? "\u2605" : "\u2606"}
                  </button>
                </div>
              </div>
              <div className="image-badges">
                <span
                  className={`rating-badge ${image.contentRating}`}
                >
                  {image.contentRating === "mature" ? "\uD83D\uDD1E" : "\u2713"}
                </span>
              </div>
            </div>
          ))}

          {filteredImages.length === 0 && (
            <div className="empty-gallery">
              <span className="empty-icon">\uD83D\uDDBC\uFE0F</span>
              <p>No images found</p>
              {filter !== "all" && (
                <button onClick={() => setFilter("all")}>Show All</button>
              )}
            </div>
          )}
        </div>

        {/* Detail Panel */}
        {selectedImage && (
          <div className="detail-panel">
            <div className="detail-image">
              <img src={selectedImage.url} alt="Selected" />
            </div>

            <div className="detail-info">
              <h3>Generation Details</h3>

              <div className="info-group">
                <label>Prompt</label>
                <p className="prompt-text">{selectedImage.prompt}</p>
                <button
                  className="copy-btn"
                  onClick={() => handleCopyPrompt(selectedImage.prompt)}
                >
                  Copy Prompt
                </button>
              </div>

              {selectedImage.negativePrompt && (
                <div className="info-group">
                  <label>Negative Prompt</label>
                  <p className="prompt-text negative">
                    {selectedImage.negativePrompt}
                  </p>
                </div>
              )}

              <div className="info-grid">
                <div className="info-item">
                  <label>Model</label>
                  <span>{selectedImage.modelId}</span>
                </div>
                <div className="info-item">
                  <label>Size</label>
                  <span>
                    {selectedImage.settings.width}x{selectedImage.settings.height}
                  </span>
                </div>
                <div className="info-item">
                  <label>Steps</label>
                  <span>{selectedImage.settings.steps}</span>
                </div>
                <div className="info-item">
                  <label>CFG</label>
                  <span>{selectedImage.settings.cfg}</span>
                </div>
                <div className="info-item">
                  <label>Sampler</label>
                  <span>{selectedImage.settings.sampler}</span>
                </div>
                <div className="info-item">
                  <label>Seed</label>
                  <span>{selectedImage.settings.seed}</span>
                </div>
                <div className="info-item">
                  <label>Rating</label>
                  <span className={selectedImage.contentRating}>
                    {selectedImage.contentRating.toUpperCase()}
                  </span>
                </div>
                <div className="info-item">
                  <label>Created</label>
                  <span>
                    {new Date(selectedImage.timestamp).toLocaleString()}
                  </span>
                </div>
              </div>

              <div className="detail-actions">
                <button
                  className="action-btn primary"
                  onClick={() =>
                    handleDownload(
                      selectedImage.url,
                      `generation_${selectedImage.id}.png`
                    )
                  }
                >
                  \uD83D\uDCE5 Download
                </button>
                <button
                  className={`action-btn ${selectedImage.favorite ? "active" : ""}`}
                  onClick={() => toggleFavorite(selectedImage.id)}
                >
                  {selectedImage.favorite ? "\u2605 Favorited" : "\u2606 Favorite"}
                </button>
                <button
                  className="action-btn danger"
                  onClick={() => {
                    removeGeneratedImage(selectedImage.id);
                    setSelectedImageId(null);
                  }}
                >
                  \uD83D\uDDD1 Delete
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      <style>{`
        .gallery-page {
          display: flex;
          flex-direction: column;
          height: 100%;
          padding: 24px;
        }

        .gallery-header {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 20px;
        }

        .gallery-header h2 {
          margin: 0;
          font-size: 24px;
          color: var(--color-text);
        }

        .image-count {
          color: var(--color-text-muted);
          font-size: 14px;
        }

        .gallery-filters {
          display: flex;
          gap: 12px;
          margin-bottom: 20px;
          flex-wrap: wrap;
        }

        .search-input {
          flex: 1;
          min-width: 200px;
          padding: 10px 14px;
          border: 1px solid var(--color-border);
          border-radius: 8px;
          background: var(--color-surface);
          color: var(--color-text);
          font-size: 14px;
        }

        .filter-group {
          display: flex;
          gap: 8px;
        }

        .filter-group select {
          padding: 10px 14px;
          border: 1px solid var(--color-border);
          border-radius: 8px;
          background: var(--color-surface);
          color: var(--color-text);
          font-size: 14px;
        }

        .clear-btn {
          padding: 10px 14px;
          border: 1px solid var(--color-danger);
          border-radius: 8px;
          background: transparent;
          color: var(--color-danger);
          font-size: 14px;
          cursor: pointer;
        }

        .clear-btn:hover {
          background: var(--color-danger);
          color: white;
        }

        .gallery-content {
          flex: 1;
          display: flex;
          gap: 20px;
          overflow: hidden;
        }

        .gallery-grid {
          flex: 1;
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
          gap: 16px;
          overflow-y: auto;
          padding-right: 8px;
        }

        .gallery-item {
          position: relative;
          aspect-ratio: 3/4;
          border-radius: 12px;
          overflow: hidden;
          cursor: pointer;
          border: 2px solid transparent;
          transition: all 0.2s;
        }

        .gallery-item:hover {
          border-color: var(--color-primary);
          transform: translateY(-2px);
        }

        .gallery-item.selected {
          border-color: var(--color-primary);
          box-shadow: 0 0 0 2px var(--color-primary-light);
        }

        .image-wrapper {
          width: 100%;
          height: 100%;
          position: relative;
        }

        .image-wrapper img {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }

        .image-overlay {
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          padding: 8px;
          display: flex;
          justify-content: flex-end;
          opacity: 0;
          transition: opacity 0.2s;
        }

        .gallery-item:hover .image-overlay {
          opacity: 1;
        }

        .fav-btn {
          background: rgba(0, 0, 0, 0.5);
          border: none;
          color: white;
          width: 32px;
          height: 32px;
          border-radius: 50%;
          cursor: pointer;
          font-size: 16px;
        }

        .fav-btn.active {
          color: #F59E0B;
        }

        .image-badges {
          position: absolute;
          bottom: 8px;
          left: 8px;
          display: flex;
          gap: 4px;
        }

        .rating-badge {
          padding: 4px 8px;
          border-radius: 4px;
          font-size: 12px;
          font-weight: 500;
        }

        .rating-badge.sfw {
          background: rgba(16, 185, 129, 0.9);
          color: white;
        }

        .rating-badge.mature {
          background: linear-gradient(135deg, #8B5CF6, #F59E0B);
          color: white;
        }

        .empty-gallery {
          grid-column: 1 / -1;
          text-align: center;
          padding: 60px 20px;
          color: var(--color-text-muted);
        }

        .empty-icon {
          font-size: 48px;
          display: block;
          margin-bottom: 12px;
        }

        .detail-panel {
          width: 360px;
          background: var(--color-surface);
          border-radius: 12px;
          border: 1px solid var(--color-border);
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }

        .detail-image {
          aspect-ratio: 3/4;
          max-height: 300px;
          overflow: hidden;
        }

        .detail-image img {
          width: 100%;
          height: 100%;
          object-fit: cover;
        }

        .detail-info {
          padding: 16px;
          overflow-y: auto;
          flex: 1;
        }

        .detail-info h3 {
          margin: 0 0 16px;
          font-size: 16px;
          color: var(--color-text);
        }

        .info-group {
          margin-bottom: 16px;
        }

        .info-group label {
          display: block;
          font-size: 12px;
          font-weight: 500;
          color: var(--color-text-muted);
          margin-bottom: 6px;
        }

        .prompt-text {
          margin: 0;
          font-size: 13px;
          line-height: 1.5;
          color: var(--color-text);
          background: var(--color-background);
          padding: 10px;
          border-radius: 6px;
          max-height: 100px;
          overflow-y: auto;
        }

        .prompt-text.negative {
          color: var(--color-text-muted);
          font-size: 12px;
        }

        .copy-btn {
          margin-top: 8px;
          padding: 6px 12px;
          font-size: 12px;
          border: 1px solid var(--color-border);
          border-radius: 6px;
          background: var(--color-surface);
          color: var(--color-text-muted);
          cursor: pointer;
        }

        .copy-btn:hover {
          background: var(--color-surface-hover);
        }

        .info-grid {
          display: grid;
          grid-template-columns: repeat(2, 1fr);
          gap: 12px;
          margin-bottom: 20px;
        }

        .info-item {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .info-item label {
          font-size: 11px;
          color: var(--color-text-muted);
          text-transform: uppercase;
        }

        .info-item span {
          font-size: 13px;
          color: var(--color-text);
          word-break: break-all;
        }

        .info-item span.sfw {
          color: #10B981;
        }

        .info-item span.mature {
          color: #F59E0B;
        }

        .detail-actions {
          display: flex;
          flex-direction: column;
          gap: 8px;
        }

        .action-btn {
          padding: 10px 16px;
          border: 1px solid var(--color-border);
          border-radius: 8px;
          background: var(--color-surface);
          color: var(--color-text);
          font-size: 14px;
          cursor: pointer;
          transition: all 0.2s;
        }

        .action-btn:hover {
          background: var(--color-surface-hover);
        }

        .action-btn.primary {
          background: var(--color-primary);
          border-color: var(--color-primary);
          color: white;
        }

        .action-btn.primary:hover {
          background: var(--color-primary-hover);
        }

        .action-btn.active {
          background: #FEF3C7;
          border-color: #F59E0B;
          color: #92400E;
        }

        .action-btn.danger {
          border-color: var(--color-danger);
          color: var(--color-danger);
        }

        .action-btn.danger:hover {
          background: var(--color-danger);
          color: white;
        }

        @media (max-width: 1024px) {
          .detail-panel {
            position: fixed;
            right: 0;
            top: 0;
            bottom: 0;
            z-index: 100;
            border-radius: 0;
            border-left: 1px solid var(--color-border);
          }
        }
      `}</style>
    </div>
  );
};

export default GalleryPage;
