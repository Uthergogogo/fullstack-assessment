# Variant PDP frontend

Use Node.js 22.12 or later. Start the [API](../backend/README.md) on port 8000 first, then run these commands from the repository root.

```powershell
npm.cmd --prefix app/frontend ci
npm.cmd --prefix app/frontend run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` and `/images` from the same origin so the browser can keep the anonymous cart cookie. Set `PDP_API_ORIGIN` before starting Vite if the API uses a different address. [Vite proxy configuration](https://vite.dev/config/server-options#server-proxy)

```powershell
npm.cmd --prefix app/frontend test
npm.cmd --prefix app/frontend run build
npm.cmd --prefix app/frontend run preview
```

The test and build commands work without a running API. The preview command serves the build and uses the same backend proxy as the development server. Dependencies and exact resolved versions are listed in `package.json` and `package-lock.json`.

## Behaviour

- `api.ts` handles requests, validates response shapes and normalises API errors. `variants.ts` resolves available options and quantity bounds. The React components handle selection and purchase feedback.
- The page derives price, image and stock from the current selection. Missing and disabled combinations are unavailable. An active SKU with zero inventory can still be inspected. A quantity carries over to another in-stock SKU within that SKU's limits.
- A synchronous submission guard covers the interval before React renders the disabled control. After an uncertain write, **Retry add** reuses the original payload, key and cart context while the page remains open. A confirmed replay triggers fresh reads, since the replay response can contain older stock and cart data. A changed cart context also triggers fresh reads and leaves the decision to start a new add with the shopper. If those reads fail, the next retry only refreshes the stock and cart.
- After a focused add or retry action completes, keyboard focus goes to the retry button, the available add button or the feedback area, depending on the outcome.
- An insufficient-stock response can supply the current quantity directly. The UI updates that SKU, adjusts the requested quantity, and lets the shopper try again from the same page. A subsequent add uses a new key.
