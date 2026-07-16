# HomePilot content notices

This folder contains an additive, framework-independent notice layer for hosted HomePilot deployments.

It presents HomePilot as a general-purpose AI platform for work, productivity, creativity, assistance, and companionship. Mature settings remain optional and separate from the standard SFW experience.

## Included notices

- A neutral first-visit welcome notice.
- An explicit adult-confirmation dialog that appears only when mature mode is requested.
- Accessible keyboard focus handling and responsive styling.
- Browser-local consent storage. No personal information is transmitted.

## Integration

The DigitalOcean wrapper image copies these assets into the compiled HomePilot frontend and injects the required `<link>` and `<script>` tags into `index.html`. Existing frontend source files are not changed.

To request consent from an existing mature-mode control:

```js
window.dispatchEvent(new CustomEvent("homepilot:mature-mode-requested"));

window.addEventListener("homepilot:mature-mode-consent", (event) => {
  if (event.detail.accepted) {
    // Enable the optional mature setting.
  }
});
```

The same behavior can be called directly:

```js
const accepted = await window.HomePilotNotifications.openMatureConsent();
```

Check or revoke consent with:

```js
window.HomePilotNotifications.hasMatureConsent();
window.HomePilotNotifications.clearMatureConsent();
```

The notice is a user-interface safeguard, not a substitute for server-side policy enforcement, content moderation, or legally required age-assurance controls.