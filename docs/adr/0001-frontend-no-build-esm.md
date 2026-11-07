# Frontend is plain React served as native ES modules, no bundler

The feed UI moves off Vite, TypeScript, zustand, TanStack Query/Virtual and axios to React loaded as vendored ES modules with `htm` templates and JSDoc types, served directly by FastAPI. Chosen to remove the Node build from the viewer image and keep the stack to what React itself provides. Fix search and scoring bugs on the current FE first, then build the new FE in a separate directory and swap at parity.

## Consequences

- No `tsc` safety net: types are JSDoc only.
- Long lists use pagination, not virtualization.
- Reverting means reintroducing a build step, so keep component code JSX-portable.
