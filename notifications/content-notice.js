(() => {
  "use strict";

  const WELCOME_KEY = "homepilot.notice.welcome.v1";
  const MATURE_KEY = "homepilot.notice.mature-consent.v1";
  const config = Object.assign(
    {
      showWelcome: true,
      welcomeDelayMs: 250,
    },
    window.HomePilotNoticeConfig || {},
  );

  let activeModal = null;
  let previousFocus = null;

  function closeModal(result) {
    if (!activeModal) return;
    const { backdrop, resolve } = activeModal;
    activeModal = null;
    backdrop.remove();
    document.body.style.removeProperty("overflow");
    if (previousFocus && typeof previousFocus.focus === "function") {
      previousFocus.focus();
    }
    previousFocus = null;
    if (resolve) resolve(result);
  }

  function createModal({ eyebrow, title, copy, list = [], finePrint, actions }) {
    if (activeModal) closeModal(false);

    previousFocus = document.activeElement;
    const backdrop = document.createElement("div");
    backdrop.className = "hp-notice-backdrop";

    const dialog = document.createElement("section");
    dialog.className = "hp-notice-dialog";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-labelledby", "hp-notice-title");

    const body = document.createElement("div");
    body.className = "hp-notice-body";

    if (eyebrow) {
      const eyebrowNode = document.createElement("p");
      eyebrowNode.className = "hp-notice-eyebrow";
      eyebrowNode.textContent = eyebrow;
      body.appendChild(eyebrowNode);
    }

    const titleNode = document.createElement("h2");
    titleNode.id = "hp-notice-title";
    titleNode.className = "hp-notice-title";
    titleNode.textContent = title;
    body.appendChild(titleNode);

    copy.forEach((paragraph) => {
      const node = document.createElement("p");
      node.className = "hp-notice-copy";
      node.textContent = paragraph;
      body.appendChild(node);
    });

    if (list.length) {
      const listNode = document.createElement("ul");
      listNode.className = "hp-notice-list";
      list.forEach((item) => {
        const itemNode = document.createElement("li");
        itemNode.textContent = item;
        listNode.appendChild(itemNode);
      });
      body.appendChild(listNode);
    }

    if (finePrint) {
      const finePrintNode = document.createElement("p");
      finePrintNode.className = "hp-notice-fine-print";
      finePrintNode.textContent = finePrint;
      body.appendChild(finePrintNode);
    }

    const actionsNode = document.createElement("div");
    actionsNode.className = "hp-notice-actions";

    actions.forEach((action) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `hp-notice-button hp-notice-button--${action.kind || "secondary"}`;
      button.textContent = action.label;
      button.addEventListener("click", action.onClick);
      actionsNode.appendChild(button);
    });

    dialog.append(body, actionsNode);
    backdrop.appendChild(dialog);
    document.body.appendChild(backdrop);
    document.body.style.overflow = "hidden";

    const firstButton = actionsNode.querySelector("button");
    if (firstButton) firstButton.focus();

    backdrop.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeModal(false);
      if (event.key !== "Tab") return;

      const focusable = Array.from(dialog.querySelectorAll("button"));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

    return backdrop;
  }

  function openWelcome(force = false) {
    if (!force && localStorage.getItem(WELCOME_KEY) === "accepted") return;

    const backdrop = createModal({
      eyebrow: "General-purpose AI",
      title: "Welcome to HomePilot",
      copy: [
        "HomePilot supports work, productivity, creativity, assistance, and personalized AI companionship.",
        "Most features are suitable for everyday and professional use. Optional mature settings, where available, are separate from the standard experience and require adult confirmation.",
      ],
      finePrint:
        "Illegal, exploitative, non-consensual, or underage sexual content is strictly prohibited.",
      actions: [
        {
          label: "Continue",
          kind: "primary",
          onClick: () => {
            localStorage.setItem(WELCOME_KEY, "accepted");
            closeModal(true);
          },
        },
      ],
    });

    activeModal = { backdrop, resolve: null };
  }

  function openMatureConsent() {
    return new Promise((resolve) => {
      const backdrop = createModal({
        eyebrow: "Optional setting · Adults only",
        title: "Enable Mature Content Mode?",
        copy: [
          "HomePilot is primarily a general-purpose AI assistant and companionship platform. This optional mode is separate from the standard SFW workspace.",
          "Mature settings may allow adult-oriented conversations or non-explicit romantic and suggestive content. They are not required to use HomePilot.",
        ],
        list: [
          "I confirm that I am at least 18 years old.",
          "I understand that mature themes may appear.",
          "I will not create illegal, exploitative, non-consensual, or underage content.",
        ],
        finePrint: "Mature Content Mode can be disabled at any time in Settings.",
        actions: [
          {
            label: "Cancel",
            kind: "secondary",
            onClick: () => closeModal(false),
          },
          {
            label: "I’m 18+ and Enable",
            kind: "primary",
            onClick: () => {
              localStorage.setItem(
                MATURE_KEY,
                JSON.stringify({ accepted: true, acceptedAt: new Date().toISOString() }),
              );
              closeModal(true);
            },
          },
        ],
      });

      activeModal = { backdrop, resolve };
    });
  }

  function hasMatureConsent() {
    try {
      const value = JSON.parse(localStorage.getItem(MATURE_KEY) || "null");
      return Boolean(value && value.accepted === true);
    } catch (_) {
      return false;
    }
  }

  function clearMatureConsent() {
    localStorage.removeItem(MATURE_KEY);
  }

  window.HomePilotNotifications = Object.freeze({
    openWelcome,
    openMatureConsent,
    hasMatureConsent,
    clearMatureConsent,
  });

  window.addEventListener("homepilot:mature-mode-requested", async () => {
    const accepted = hasMatureConsent() || (await openMatureConsent());
    window.dispatchEvent(
      new CustomEvent("homepilot:mature-mode-consent", { detail: { accepted } }),
    );
  });

  function start() {
    if (!config.showWelcome) return;
    window.setTimeout(() => openWelcome(false), Number(config.welcomeDelayMs) || 0);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
