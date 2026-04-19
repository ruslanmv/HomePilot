/**
 * Shared presentation primitives for the Interactive tab.
 *
 * Why one file for the lot: the Interactive surface re-uses the
 * same 6 primitives dozens of times (toast, button, panel, empty
 * state, skeleton, status badge). Keeping them co-located keeps
 * the import surface narrow and the visual language tight:
 *
 *   bg tokens:   #0f0f0f / #1a1a1a / #1f1f1f / #121212
 *   borders:     #3f3f3f (default), #555 (hover)
 *   accent:      #3ea6ff  → selected/ring/primary-CTA color
 *   text tokens: #f1f1f1 (primary), #aaa (secondary), #777 (tertiary)
 *
 * Accessibility:
 *   - `PrimaryButton` + `SecondaryButton` always render a <button>,
 *     never a div; visible focus ring is driven by the default
 *     Tailwind `focus-visible` utility.
 *   - Toasts use `role="status"` with `aria-live="polite"` so
 *     screen readers announce them without stealing focus.
 *   - All interactive cards expose `aria-label` and render as
 *     <button type="button"> so keyboard users get Enter/Space.
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle, X } from "lucide-react";
import type { ExperienceStatus } from "./types";

// ────────────────────────────────────────────────────────────────
// Buttons
// ────────────────────────────────────────────────────────────────

type ButtonSize = "sm" | "md" | "lg";

type BaseButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  size?: ButtonSize;
  loading?: boolean;
  icon?: React.ReactNode;
};

const SIZE_CLASSES: Record<ButtonSize, string> = {
  sm: "px-2.5 py-1.5 text-xs",
  md: "px-3.5 py-2 text-sm",
  lg: "px-4 py-2.5 text-base",
};

export function PrimaryButton({
  size = "md", loading, icon, children, className, disabled, ...rest
}: BaseButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={[
        "inline-flex items-center gap-2 rounded-md font-medium",
        "bg-[#3ea6ff] text-black",
        "hover:bg-[#62b6ff] active:bg-[#2f8fe3]",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        "transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0f0f0f]",
        SIZE_CLASSES[size],
        className || "",
      ].join(" ")}
      {...rest}
    >
      {loading ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

export function SecondaryButton({
  size = "md", loading, icon, children, className, disabled, ...rest
}: BaseButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={[
        "inline-flex items-center gap-2 rounded-md font-medium",
        "bg-[#1f1f1f] text-[#f1f1f1] border border-[#3f3f3f]",
        "hover:bg-[#282828] hover:border-[#555]",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        "transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] focus-visible:ring-offset-2 focus-visible:ring-offset-[#0f0f0f]",
        SIZE_CLASSES[size],
        className || "",
      ].join(" ")}
      {...rest}
    >
      {loading ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

export function DangerButton({
  size = "md", loading, icon, children, className, disabled, ...rest
}: BaseButtonProps) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={[
        "inline-flex items-center gap-2 rounded-md font-medium",
        "bg-transparent text-red-400 border border-red-500/40",
        "hover:bg-red-500/10 hover:border-red-500/70",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        "transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0f0f0f]",
        SIZE_CLASSES[size],
        className || "",
      ].join(" ")}
      {...rest}
    >
      {loading ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

// ────────────────────────────────────────────────────────────────
// Panel — titled section wrapper used by editor tabs
// ────────────────────────────────────────────────────────────────

export function Panel({
  title, subtitle, actions, children, className,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={[
        "bg-[#1a1a1a] border border-[#3f3f3f] rounded-lg",
        className || "",
      ].join(" ")}
    >
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 px-5 py-4 border-b border-[#3f3f3f]">
          <div>
            {title && <h2 className="text-sm font-semibold text-[#f1f1f1]">{title}</h2>}
            {subtitle && <p className="mt-1 text-xs text-[#aaa]">{subtitle}</p>}
          </div>
          {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  );
}

// ────────────────────────────────────────────────────────────────
// EmptyState
// ────────────────────────────────────────────────────────────────

export function EmptyState({
  icon, title, description, action,
}: {
  icon: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="border border-dashed border-[#3f3f3f] rounded-lg p-10 text-center bg-[#151515]">
      <div className="w-12 h-12 mx-auto text-[#3ea6ff] mb-3" aria-hidden>
        {icon}
      </div>
      <div className="text-base font-medium text-[#f1f1f1]">{title}</div>
      {description && (
        <p className="text-sm text-[#aaa] mt-1 max-w-md mx-auto">{description}</p>
      )}
      {action && <div className="mt-5 flex justify-center">{action}</div>}
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// Skeleton loaders (grid card + list row)
// ────────────────────────────────────────────────────────────────

export function SkeletonCard() {
  return (
    <div
      className="bg-[#1f1f1f] border border-[#3f3f3f] rounded-lg p-5 animate-pulse"
      role="status" aria-label="Loading project"
    >
      <div className="h-4 bg-[#2a2a2a] rounded w-3/4 mb-3" />
      <div className="h-3 bg-[#2a2a2a] rounded w-full mb-2" />
      <div className="h-3 bg-[#2a2a2a] rounded w-5/6 mb-4" />
      <div className="flex gap-2">
        <div className="h-3 bg-[#2a2a2a] rounded w-16" />
        <div className="h-3 bg-[#2a2a2a] rounded w-20" />
      </div>
    </div>
  );
}

export function SkeletonRow() {
  return (
    <div
      className="bg-[#1f1f1f] border border-[#3f3f3f] rounded p-3 animate-pulse flex gap-3 items-center"
      role="status" aria-label="Loading row"
    >
      <div className="h-4 bg-[#2a2a2a] rounded w-24" />
      <div className="h-4 bg-[#2a2a2a] rounded flex-1" />
      <div className="h-4 bg-[#2a2a2a] rounded w-12" />
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// ErrorBanner — inline retriable error
// ────────────────────────────────────────────────────────────────

export function ErrorBanner({
  title = "Something went wrong", message, onRetry,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="border border-red-500/40 bg-red-500/5 rounded-md p-4 flex gap-3 items-start"
    >
      <AlertTriangle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" aria-hidden />
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-red-400">{title}</div>
        <p className="text-xs text-red-300/80 mt-1 break-words">{message}</p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-3 text-xs font-medium text-[#3ea6ff] hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] rounded"
          >
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// StatusBadge
// ────────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<ExperienceStatus, string> = {
  draft: "text-yellow-300 bg-yellow-400/10 border-yellow-400/30",
  in_review: "text-blue-300 bg-blue-400/10 border-blue-400/30",
  approved: "text-emerald-300 bg-emerald-400/10 border-emerald-400/30",
  archived: "text-[#aaa] bg-white/5 border-white/10",
  published: "text-green-300 bg-green-400/10 border-green-400/30",
};

const STATUS_LABEL: Record<ExperienceStatus, string> = {
  draft: "Draft",
  in_review: "In review",
  approved: "Approved",
  archived: "Archived",
  published: "Published",
};

export function StatusBadge({ status }: { status: ExperienceStatus }) {
  return (
    <span
      className={[
        "text-[10px] uppercase tracking-wide px-2 py-0.5 rounded border",
        STATUS_STYLES[status] || STATUS_STYLES.draft,
      ].join(" ")}
    >
      {STATUS_LABEL[status] || status}
    </span>
  );
}

// ────────────────────────────────────────────────────────────────
// Toast system — accessible, auto-dismissing
// ────────────────────────────────────────────────────────────────

type ToastVariant = "success" | "error" | "info" | "warning";

interface ToastItem {
  id: number;
  variant: ToastVariant;
  title: string;
  message?: string;
  timeoutMs: number;
}

interface ToastContextValue {
  toast(t: { variant?: ToastVariant; title: string; message?: string; timeoutMs?: number }): void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    // Graceful no-op when the provider isn't mounted, so individual
    // panels stay testable outside <ToastProvider>.
    return {
      toast({ title }) {
        // eslint-disable-next-line no-console
        console.info(`[toast] ${title}`);
      },
    };
  }
  return ctx;
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);

  const remove = useCallback((id: number) => {
    setItems((xs) => xs.filter((x) => x.id !== id));
  }, []);

  const toast = useCallback<ToastContextValue["toast"]>((t) => {
    const id = Date.now() + Math.random();
    const next: ToastItem = {
      id,
      variant: t.variant ?? "info",
      title: t.title,
      message: t.message,
      timeoutMs: t.timeoutMs ?? (t.variant === "error" ? 6000 : 3500),
    };
    setItems((xs) => [...xs, next]);
    window.setTimeout(() => remove(id), next.timeoutMs);
  }, [remove]);

  const ctx = useMemo<ToastContextValue>(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={ctx}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2 pointer-events-none"
      >
        {items.map((item) => (
          <ToastCard key={item.id} item={item} onClose={() => remove(item.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastCard({ item, onClose }: { item: ToastItem; onClose: () => void }) {
  const palette: Record<ToastVariant, { border: string; bg: string; icon: React.ReactNode }> = {
    success: {
      border: "border-emerald-500/40", bg: "bg-emerald-500/10",
      icon: <CheckCircle2 className="w-4 h-4 text-emerald-400" />,
    },
    error: {
      border: "border-red-500/40", bg: "bg-red-500/10",
      icon: <XCircle className="w-4 h-4 text-red-400" />,
    },
    warning: {
      border: "border-amber-500/40", bg: "bg-amber-500/10",
      icon: <AlertTriangle className="w-4 h-4 text-amber-400" />,
    },
    info: {
      border: "border-[#3ea6ff]/40", bg: "bg-[#3ea6ff]/10",
      icon: <Info className="w-4 h-4 text-[#3ea6ff]" />,
    },
  };
  const p = palette[item.variant];
  return (
    <div
      role="status"
      className={[
        "pointer-events-auto min-w-[260px] max-w-sm rounded-md backdrop-blur-sm",
        "border px-3 py-2.5 flex items-start gap-3 shadow-lg",
        p.border, p.bg,
      ].join(" ")}
    >
      <div className="mt-0.5">{p.icon}</div>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-[#f1f1f1]">{item.title}</div>
        {item.message && (
          <div className="text-xs text-[#cfd8dc] mt-0.5 break-words">{item.message}</div>
        )}
      </div>
      <button
        type="button"
        onClick={onClose}
        aria-label="Dismiss notification"
        className="text-[#aaa] hover:text-[#f1f1f1] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] rounded"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

// ────────────────────────────────────────────────────────────────
// useAsyncResource — data loader with loading/error/data states
// ────────────────────────────────────────────────────────────────

export interface AsyncResource<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
  setData: React.Dispatch<React.SetStateAction<T | null>>;
}

export function useAsyncResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: React.DependencyList,
): AsyncResource<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [token, setToken] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    let cancelled = false;
    setLoading(true);
    setError(null);
    load(ctrl.signal)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: Error) => {
        if (!cancelled && err.name !== "AbortError") {
          setError(err.message || "Unexpected error");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      ctrl.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, token]);

  const reload = useCallback(() => setToken((t) => t + 1), []);
  return { data, loading, error, reload, setData };
}

// ────────────────────────────────────────────────────────────────
// Modal — accessible dialog with backdrop + ESC to close
// ────────────────────────────────────────────────────────────────

export function Modal({
  open, onClose, title, children, footer, widthClass = "max-w-lg",
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  widthClass?: string;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4"
      role="dialog" aria-modal="true" aria-label={title}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className={[
          "w-full bg-[#1a1a1a] border border-[#3f3f3f] rounded-lg shadow-2xl",
          widthClass,
        ].join(" ")}
      >
        <header className="flex items-center justify-between px-5 py-3 border-b border-[#3f3f3f]">
          <h2 className="text-sm font-semibold text-[#f1f1f1]">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="text-[#aaa] hover:text-[#f1f1f1] focus:outline-none focus-visible:ring-2 focus-visible:ring-[#3ea6ff] rounded p-1"
          >
            <X className="w-4 h-4" />
          </button>
        </header>
        <div className="px-5 py-4 max-h-[70vh] overflow-y-auto">{children}</div>
        {footer && (
          <footer className="flex items-center justify-end gap-2 px-5 py-3 border-t border-[#3f3f3f]">
            {footer}
          </footer>
        )}
      </div>
    </div>
  );
}
