import { defineConfig } from 'orval'

// Generates typed TanStack Query hooks from the backend OpenAPI schema.
// Refresh: export the schema from the backend (see CLAUDE.md), then `npm run api:generate`.
export default defineConfig({
  grafikomat: {
    input: { target: './openapi.json' },
    output: {
      mode: 'tags-split',
      target: 'src/api/generated',
      schemas: 'src/api/generated/model',
      client: 'react-query',
      httpClient: 'fetch',
      clean: true,
      override: {
        mutator: { path: 'src/api/http.ts', name: 'apiFetch' },
      },
    },
  },
})
