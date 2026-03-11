# HomePilot — Future Release TODO

> Tracking upcoming improvements, migrations, and production hardening tasks.

---

## Avatar Studio — Edit Integration Workflows

> Workflows created as JSON templates in `workflows/avatar/`. These need to be
> wired into the Avatar Studio Editor UI.

### Ready (workflow JSONs exist, need UI wiring)

- [ ] **WF-12 Inpaint Outfit** — Replace clothing via mask-guided inpainting
- [ ] **WF-14 Expression Change** — Change facial expression via face-region inpainting
- [ ] **WF-10 FaceSwap Repair** — Swap face from identity anchor onto generated body
- [ ] **WF-11 Identity Reprojection** — Subtle identity correction via img2img + InstantID
- [ ] **WF-13 Background Replace** — Auto-segment character, replace background
- [ ] **WF-15 Pose Adjustment** — Re-pose character using OpenPose ControlNet

### Advanced presets (workflow JSONs exist)

- [ ] **WF-05 Body + Pose** — Body generation with pose skeleton (needs OpenPose ControlNet)
- [ ] **WF-06 Body SDXL** — Higher quality body via SDXL
- [ ] **WF-16 Portrait** — Square headshot from face reference

### Models needed for full edit pipeline

- [ ] ControlNet OpenPose (SD1.5) — pose-guided generation
- [ ] ControlNet Depth (SD1.5) — depth-guided body generation
- [ ] Segment Anything (SAM) — automatic person/clothing segmentation
- [ ] CLIP Interrogator — prompt extraction from existing images

---

## GitHub Actions — Future Improvements

- [ ] Scheduled workflow to verify R2 registry integrity (weekly)
- [ ] Persona removal workflow (triggered by `persona-removed` label)
- [ ] Download metrics — update counts in registry
- [ ] Wrangler auto-deploy for Worker on push to `master`
- [ ] Pages auto-deploy for gallery on push to `master`

---

## Community Gallery — Future

- [ ] Upload form — submit personas from gallery page without CLI
- [ ] Moderation pipeline — approve/reject queue before listing
- [ ] SHA256 integrity verification on download
- [ ] Delta updates — download only changed files between versions
- [ ] Featured personas and popularity sorting
- [ ] Rating system
- [ ] Update notifications for installed personas
- [ ] Persona collections / curated lists

---

## Infrastructure

- [ ] Custom domain for Worker or R2 bucket
- [ ] Monitoring / alerting for gallery uptime
- [ ] Automated backup of R2 registry data

---

## Platform

- [ ] Persona versioning — update installed personas from gallery
- [ ] Dependency auto-resolver — auto-install missing models/tools
- [ ] Gallery analytics — download counts, popular tags
- [ ] Multi-language persona support

---

## Multi-User Accounts & Onboarding — Remaining

- [ ] `POST /v1/auth/forgot-password` — send reset email
- [ ] `user_id` foreign key added to: projects, conversations, profile, persona_sessions
- [ ] User switcher in sidebar (avatar + dropdown)
- [ ] All API calls include `Authorization: Bearer <token>` header

---

## Synthetic Avatar Generator (Optional Extra Package)

> Status: Planned | Priority: Medium

Optional pipeline for photorealistic synthetic face portraits using
StyleGAN2, InstantID, PhotoMaker V2, and face swap workflows.

### Implementation phases

- [ ] Phase 1: Backend model registry extension (add avatar generation category)
- [ ] Phase 2: StyleGAN2 inference service (random face generation)
- [ ] Phase 3: ComfyUI identity-preserving workflows (InstantID, PhotoMaker, face swap)
- [ ] Phase 4: Frontend UI integration (Portrait Studio mode in PersonaWizard)
- [ ] Phase 5: Packaging & distribution (model downloads, availability checks)

---

## Teams Meeting Bridge — Remaining

- [ ] Azure Entra app registration (manual — Azure Portal)
- [ ] ACS resource provisioning (manual — Azure Portal)
- [ ] Wire `azure-communication-calling` SDK into ACS client
