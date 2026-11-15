# HandOver public site

This directory is the standalone static landing page. The actual learner and teacher product remains in `web/` and the native clients.

```sh
cd site
npm run check
```

The zero-dependency build copies the site-owned, repository-sourced product visuals into `dist/assets/product` and emits a standalone deployable `dist/`. Vercel configuration is kept in `vercel.json`; building does not deploy.

Keep the landing sparse. Technical setup, architecture, privacy, compatibility, and troubleshooting belong in the repository docs linked from the page. New visuals must be real repository media and documented in `SCREENSHOTS.md`.
