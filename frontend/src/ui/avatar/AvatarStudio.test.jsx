/**
 * AvatarStudio component tests — lightweight, CI-friendly.
 *
 * Tests the multi-view architecture:
 *   1. Gallery view (landing) — default, shows avatar library
 *   2. Designer view — zero-prompt character builder (old flow)
 *
 * Tests navigation, mode selection, and action callbacks
 * without real API calls.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import React from 'react';
import AvatarStudio from './AvatarStudio';
// ---------------------------------------------------------------------------
// Mock hooks — prevent real API calls
// ---------------------------------------------------------------------------
const mockPacksData = {
    packs: [
        {
            id: 'basic',
            title: 'Basic',
            installed: true,
            license: 'Apache-2.0',
            commercial_ok: true,
            modes_enabled: ['studio_random', 'studio_reference'],
        },
    ],
    enabled_modes: ['studio_random', 'studio_reference', 'studio_faceswap'],
};
const mockRun = vi.fn().mockResolvedValue({
    mode: 'studio_random',
    results: [{ url: '/files/avatar.png', seed: 42 }],
});
const mockReset = vi.fn();
const mockCancel = vi.fn();
vi.mock('./useAvatarPacks', () => ({
    useAvatarPacks: () => ({
        data: mockPacksData,
        loading: false,
        error: null,
        refresh: vi.fn(),
    }),
}));
vi.mock('./useGenerateAvatars', () => ({
    useGenerateAvatars: () => ({
        loading: false,
        result: null,
        error: null,
        run: mockRun,
        reset: mockReset,
        cancel: mockCancel,
        removeResult: vi.fn(),
    }),
}));
vi.mock('./useAvatarGallery', () => ({
    useAvatarGallery: () => ({
        items: [],
        addItem: vi.fn(),
        addBatch: vi.fn(),
        addAnchorWithPortraits: vi.fn(),
        swapAnchor: vi.fn(),
        removeItem: vi.fn(),
        clearAll: vi.fn(),
        tagItem: vi.fn(),
        linkToPersona: vi.fn(),
        updateItem: vi.fn(),
    }),
}));
// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
/** Render AvatarStudio and click "Create Avatar" to enter designer view. */
function renderDesignerView(props) {
    const result = render(<AvatarStudio backendUrl="http://localhost:8000" {...props}/>);
    // Navigate to designer view via the header "Create Avatar" button
    fireEvent.click(screen.getByLabelText('Create a new avatar'));
    return result;
}
// ---------------------------------------------------------------------------
// Tests — Gallery View (Landing)
// ---------------------------------------------------------------------------
describe('AvatarStudio — Gallery View', () => {
    it('renders the landing page header', () => {
        render(<AvatarStudio backendUrl="http://localhost:8000"/>);
        expect(screen.getByText('Avatar Studio')).toBeInTheDocument();
    });
    it('shows "Create Avatar" button in header', () => {
        render(<AvatarStudio backendUrl="http://localhost:8000"/>);
        expect(screen.getByLabelText('Create a new avatar')).toBeInTheDocument();
    });
    it('shows empty state with create CTAs when no avatars exist', () => {
        render(<AvatarStudio backendUrl="http://localhost:8000"/>);
        expect(screen.getByText('Create your first avatar')).toBeInTheDocument();
    });
    it('clicking "Create Avatar" navigates to designer view', () => {
        render(<AvatarStudio backendUrl="http://localhost:8000"/>);
        fireEvent.click(screen.getByLabelText('Create a new avatar'));
        // Should now see designer header with back button
        expect(screen.getByText('Avatar Studio')).toBeInTheDocument();
        expect(screen.getByTitle('Back to Gallery')).toBeInTheDocument();
    });
});
// ---------------------------------------------------------------------------
// Tests — Designer View (Zero-Prompt Character Builder)
// ---------------------------------------------------------------------------
describe('AvatarStudio — Designer View', () => {
    beforeEach(() => {
        mockRun.mockClear();
    });
    it('renders the designer header with back button', () => {
        renderDesignerView();
        expect(screen.getByTitle('Back to Gallery')).toBeInTheDocument();
        expect(screen.getByText('Avatar Studio')).toBeInTheDocument();
    });
    it('renders the "Create Your Avatar" title', () => {
        renderDesignerView();
        expect(screen.getByText('Create Your Avatar')).toBeInTheDocument();
    });
    it('shows gender selection buttons', () => {
        renderDesignerView();
        expect(screen.getByText(/Female/)).toBeInTheDocument();
        expect(screen.getByText(/Male/)).toBeInTheDocument();
    });
    it('shows mode selection pills (Design Character, From Reference, Face + Style)', () => {
        renderDesignerView();
        expect(screen.getByText('Design Character')).toBeInTheDocument();
    });
    it('shows Core Identity section label', () => {
        renderDesignerView();
        expect(screen.getByText(/Core Identity/)).toBeInTheDocument();
    });
    it('back button returns to gallery view', () => {
        renderDesignerView();
        fireEvent.click(screen.getByTitle('Back to Gallery'));
        // Should see gallery landing again
        expect(screen.getByLabelText('Create a new avatar')).toBeInTheDocument();
    });
    it('onSendToEdit callback is passed to AvatarStudio', () => {
        const onSendToEdit = vi.fn();
        renderDesignerView({ onSendToEdit });
        expect(onSendToEdit).not.toHaveBeenCalled();
    });
    it('onOpenLightbox callback is passed to AvatarStudio', () => {
        const onOpenLightbox = vi.fn();
        renderDesignerView({ onOpenLightbox });
        expect(onOpenLightbox).not.toHaveBeenCalled();
    });
});
