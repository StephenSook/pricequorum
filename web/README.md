# PriceQuorum web

The Next.js front end for PriceQuorum. Project overview, live URL and page list: [../README.md](../README.md). API contract: [../docs/contracts/api.md](../docs/contracts/api.md).

## Run

```
npm ci
npm run dev
```

Set `NEXT_PUBLIC_API_BASE_URL` to the backend address (see `../.env.example`). Without it, every page that needs backend data says so.

## Checks

The same commands CI runs in `.github/workflows/web.yml`:

```
npm run typecheck
npm run lint
npm run test
npm run build
```

Browser smoke and accessibility against a running site (defaults to the production URL):

```
BASE_URL=http://localhost:3000 npm run e2e
```

## Deploy

Production is deployed from this directory with the Vercel CLI. The commit is stamped into the build so `deployed-smoke` can prove what is live. Deploy only a clean, pushed commit:

```
vercel --prod --build-env NEXT_PUBLIC_BUILD_SHA=$(git rev-parse HEAD)
```

## Layout

- `app/`: routes (`/`, `/runs/[id]`, `/verify`, `/evals`, `/judges`)
- `components/chapters/`: one component per run chapter, each rendered only once its events arrive
- `components/motion/`: preloader, frame and backdrop
- `lib/api/`: API client, SSE hook and run reducer
- `lib/verify/`: in-browser ledger chain and signature check
- `tests/unit/`: vitest; `tests/e2e/`: Playwright with axe
