/**
 * Studio Theme Definitions
 *
 * Two distinct visual modes:
 * - SFW: Clean, bright, professional blue
 * - Mature: Dark, sophisticated purple
 */

export const sfwTheme = {
  name: 'sfw',
  colors: {
    // Primary
    primary: '#3B82F6',
    primaryHover: '#2563EB',
    primaryLight: '#DBEAFE',

    // Background
    background: '#F8FAFC',
    surface: '#FFFFFF',
    surfaceHover: '#F1F5F9',

    // Text
    text: '#1E293B',
    textMuted: '#64748B',
    textLight: '#94A3B8',

    // Accents
    success: '#10B981',
    warning: '#F59E0B',
    danger: '#EF4444',

    // Borders
    border: '#E2E8F0',
    borderHover: '#CBD5E1',

    // Special
    badge: '#10B981',
    badgeText: '#FFFFFF',
  },
  shadows: {
    sm: '0 1px 2px rgba(0, 0, 0, 0.05)',
    md: '0 4px 6px rgba(0, 0, 0, 0.07)',
    lg: '0 10px 15px rgba(0, 0, 0, 0.1)',
  },
};

export const matureTheme = {
  name: 'mature',
  colors: {
    // Primary (Purple)
    primary: '#8B5CF6',
    primaryHover: '#7C3AED',
    primaryLight: '#2E2346',

    // Background (Dark)
    background: '#1E1B2E',
    surface: '#2A2640',
    surfaceHover: '#36324D',

    // Text
    text: '#F1F5F9',
    textMuted: '#A5A3B5',
    textLight: '#6B6980',

    // Accents
    success: '#10B981',
    warning: '#F59E0B',
    danger: '#EF4444',

    // Borders
    border: '#3D3958',
    borderHover: '#4F4A6A',

    // Special (Amber for NSFW indicators)
    badge: '#F59E0B',
    badgeText: '#1E1B2E',
  },
  shadows: {
    sm: '0 1px 2px rgba(0, 0, 0, 0.2)',
    md: '0 4px 6px rgba(0, 0, 0, 0.3)',
    lg: '0 10px 15px rgba(0, 0, 0, 0.4)',
  },
};

export type Theme = typeof sfwTheme;

export const getTheme = (contentRating: 'sfw' | 'mature'): Theme => {
  return contentRating === 'mature' ? matureTheme : sfwTheme;
};

// CSS custom properties generator
export const themeToCSS = (theme: Theme): string => {
  return `
    --color-primary: ${theme.colors.primary};
    --color-primary-hover: ${theme.colors.primaryHover};
    --color-primary-light: ${theme.colors.primaryLight};
    --color-background: ${theme.colors.background};
    --color-surface: ${theme.colors.surface};
    --color-surface-hover: ${theme.colors.surfaceHover};
    --color-text: ${theme.colors.text};
    --color-text-muted: ${theme.colors.textMuted};
    --color-text-light: ${theme.colors.textLight};
    --color-success: ${theme.colors.success};
    --color-warning: ${theme.colors.warning};
    --color-danger: ${theme.colors.danger};
    --color-border: ${theme.colors.border};
    --color-border-hover: ${theme.colors.borderHover};
    --color-badge: ${theme.colors.badge};
    --color-badge-text: ${theme.colors.badgeText};
    --shadow-sm: ${theme.shadows.sm};
    --shadow-md: ${theme.shadows.md};
    --shadow-lg: ${theme.shadows.lg};
  `;
};
