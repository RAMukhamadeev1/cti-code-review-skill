# TypeScript Code Review Guide

What the type system adds on top of JavaScript: type safety and narrowing, strict configuration, typed linting, type tests, module resolution, and TypeScript 5.x to 7.0 features and upgrades. Runtime semantics are owned by [javascript.md](javascript.md).

Load with [javascript.md](javascript.md), or with [nestjs.md](nestjs.md) for NestJS code; Node.js runtime topics are in [nodejs.md](nodejs.md).

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

Default severities: 🔴 [blocking] · 🟡 [important] · 🟢 [nit] · 💡 [suggestion]; adjust them to the impact in context. What the compiler or the lint config already reports is a finding only when the diff disables the check, and pre-existing code only when the change makes it worse.

### Type safety → [Type Safety Basics](#type-safety-basics)

- [ ] 🟡 No new `any`, explicit or leaked (`JSON.parse`, `response.json()`, untyped libraries): a real type, or `unknown` plus narrowing. `any` is fine in generic constraints (`(...args: any[]) => unknown`), test doubles, and commented interop shims.
- [ ] 🟡 No `as` assertion on external data (`response.json()`, `JSON.parse`, `req.body`, DOM queries): validate or narrow instead; `as` after a check the compiler cannot follow needs a comment.
- [ ] 🟡 Non-null `!` only where an invariant guarantees the value; `@ts-expect-error` with a reason instead of `@ts-ignore`.
- [ ] 🟡 Unions are narrowed (`typeof`, `instanceof`, `in`, `Array.isArray`, a discriminant); switches over unions are exhaustive (a `never` check for `void` functions, or `switch-exhaustiveness-check`).
- [ ] 💡 States with different data are discriminated unions; related types are derived (`Pick`, `Omit`, mapped types) rather than hand-copied; generics are constrained (`K extends keyof T`) and not added where a concrete type works.
- [ ] 💡 `satisfies` validates a literal without widening it; `as const` or a `const` type parameter keeps literal types.

### Configuration → [Strict Mode Configuration](#strict-mode-configuration)

- [ ] 🟡 When the PR touches tsconfig: `strict` stays on (the TS 6 default), and turning a strict option off has a stated reason (NestJS's `strictPropertyInitialization: false` is accepted); extra flags such as `noUncheckedIndexedAccess` are 💡 suggestions, not findings.
- [ ] 🟡 When the PR upgrades to TS 6: `types`, `rootDir`, `module`, and `target` are explicit wherever the project relied on the old defaults, and deprecated options are removed (`ignoreDeprecations` only as a temporary step with a follow-up) → [TS 6.0 defaults](#review-typescript-60-default-changes-when-upgrading).
- [ ] 🟡 When the PR moves to TS 7: every tool that imports `typescript` keeps the 6.0 API installed → [TS 7 tooling](#check-tooling-before-upgrading-to-typescript-7).

### Immutability → [Immutability](#immutability)

- [ ] 🟢 Functions that must not change their input take `readonly T[]`/`Readonly<T>`; `readonly` is compile-time only, so runtime copying follows [javascript.md](javascript.md#mutation-and-copying).

### Typed linting → [ESLint Rules](#eslint-rules)

- [ ] 🟡 `no-floating-promises`, `no-misused-promises`, and `await-thenable` stay enabled; an `eslint-disable` for them, or a `void` added only to silence one, carries a comment.
- [ ] 🟢 Style rules that no preset enables (such as `explicit-function-return-type`) are not findings unless the project turns them on.

### Tests & modules → [Testing TypeScript](#testing-typescript)

- [ ] 🟡 When the PR touches CI or test setup: `tsc --noEmit` checks sources and tests, since Vitest, transpile-only ts-jest, and Node.js type stripping run code without checking types.
- [ ] 🟡 Type-level APIs (generics, overloads, inference) have type tests that run under a type checker; negative tests use `@ts-expect-error` or `.not`.
- [ ] 🟡 Path aliases also resolve at runtime (bundler alias or `package.json` `"imports"`); `baseUrl` is a finding only on TS 6+ or before a TS 7 move → [Path aliases](#path-aliases-and-module-resolution).

### Language features → [Modern TypeScript Features](#modern-typescript-features)

- [ ] 🟡 `.ts` files that Node.js runs directly compile with `erasableSyntaxOnly` and `verbatimModuleSyntax`: no enums, runtime namespaces, parameter properties, or `import =`, and `import type` for types (not for NestJS or other `tsc`/SWC-built decorator code).
- [ ] 🟡 New decorators use the Stage 3 API, unless a dependency needs `experimentalDecorators`/`emitDecoratorMetadata` (NestJS, Angular, TypeORM, class-validator/class-transformer, TypeGraphQL, InversifyJS); with that flag on, every decorator uses the legacy signature.
- [ ] 🟡 `using`/`await using` runs natively (Node.js 24+) or is downleveled where `Symbol.dispose`/`Symbol.asyncDispose` exist, and the compiler has the `esnext` or `esnext.disposable` lib.

---

## Type Safety Basics

```typescript
// ❌ The assertion checks nothing: a payload without `email` crashes later, far from here
const user = (await response.json()) as User;
sendWelcome(user.email.toLowerCase());

// ✅ Validate at the boundary (or use a schema library); the type follows from the check
function isUser(value: unknown): value is User {
  return typeof value === 'object' && value !== null
    && 'id' in value && typeof value.id === 'string'
    && 'email' in value && typeof value.email === 'string';
}
const body: unknown = await response.json();
if (!isUser(body)) throw new Error('Unexpected user payload');
sendWelcome(body.email.toLowerCase());
```

A conditional type over a bare type parameter distributes over unions (`IsString<string | number>` is `boolean`); wrap both sides (`[T] extends [string]`) when that is not intended. An annotation such as `const palette: Record<string, string>` widens the value and accepts any key, while `satisfies` checks the shape and keeps the literal types:

```typescript
const palette = { red: '#ff0000', green: '#00ff00' } satisfies Record<string, `#${string}`>;
// palette.red is '#ff0000'; palette.blue is a compile error
```

### Make switches over unions exhaustive

A function with a non-`void` return type fails to compile ("lacks ending return statement", TS2366) when a new union member is unhandled; a `void` function gets no such error.

```typescript
type Action = { type: 'increment'; by: number } | { type: 'reset' };

function logAction(action: Action): void {
  switch (action.type) {
    case 'increment':
      console.log('increment', action.by);
      break;
    case 'reset':
      console.log('reset');
      break;
    default: {
      const unhandled: never = action; // a compile error once a new member is added
      throw new Error(`Unhandled action: ${JSON.stringify(unhandled)}`);
    }
  }
}
```

`@typescript-eslint/switch-exhaustiveness-check` does the same without the `default` branch; it is in neither the recommended nor the strict configs.

---

## Strict Mode Configuration

`"strict": true` (the TS 6 default) covers `noImplicitAny`, `strictNullChecks`, `useUnknownInCatchVariables`, and the rest of the family; listing those flags again adds nothing. Beyond it, `noUncheckedIndexedAccess` (indexing yields `T | undefined`; not part of `strict`), `noImplicitReturns`, and `noFallthroughCasesInSwitch` are 💡 suggestions, and `exactOptionalPropertyTypes` and `noPropertyAccessFromIndexSignature` are opinionated and invasive enough to suggest only for new code bases. NestJS projects set `"strictPropertyInitialization": false` (the Nest starter does) because the framework fills DTO and entity properties; accept that and keep the rest of `strict`.

---

## Immutability

A `readonly User[]` parameter makes `users.sort()` a compile error, while `users.toSorted()` (lib `es2023`+) still works. A hand-written `DeepReadonly` must leave functions alone, or methods lose their call signatures:

```typescript
type DeepReadonly<T> = T extends (...args: never[]) => unknown ? T : { readonly [K in keyof T]: DeepReadonly<T[K]> };
```

A `readonly` array constraint (`<const T extends readonly string[]>`) lets callers pass tuples whose literal types survive into the return type; with a mutable `string[]` constraint, a `const` type parameter falls back to `string[]`.

---

## ESLint Rules

Only type-checked configs see unsafe `any` flows and unhandled promises. `defineConfig()` (ESLint 9.22+) replaces the deprecated `tseslint.config()`.

```javascript
// eslint.config.js (typescript-eslint v8)
import eslint from '@eslint/js';
import { defineConfig } from 'eslint/config';
import tseslint from 'typescript-eslint';

export default defineConfig(
  eslint.configs.recommended,
  tseslint.configs.recommendedTypeChecked, // or strictTypeChecked, which contains it
  { languageOptions: { parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } } },
  {
    rules: {
      '@typescript-eslint/switch-exhaustiveness-check': 'error', // in no preset
      '@typescript-eslint/consistent-type-imports': 'error',     // in no preset
    },
  },
  // Last, so no later block re-enables a typed rule for files without type information
  { files: ['**/*.js', '**/*.mjs'], extends: [tseslint.configs.disableTypeChecked] },
);
```

`recommendedTypeChecked` already enables `no-explicit-any`, the `no-unsafe-*` rules, and the three promise rules: `no-floating-promises` (a promise not awaited, returned, or given a rejection handler), `no-misused-promises` (a promise where a `void` callback or a condition is expected, such as `items.forEach(async …)` or `if (isAllowed())` with an async `isAllowed`), and `await-thenable` (`await` on a non-promise). typescript-eslint v8 supports TypeScript `>=4.8.4 <6.1.0`, and TypeScript 7.0 ships no compiler API, so a TS 7 project keeps the 6.0 API installed for typed linting. New NestJS 12 projects lint with Oxlint, whose rule names differ. Running a linter during review is optional and only for trusted code ([javascript.md](javascript.md#linting--tooling)).

---

## Testing TypeScript

Vitest, ts-jest in transpile-only (isolated modules) mode, and Node.js type stripping all run code that `tsc` would reject, so a green test run says nothing about type errors. Runner practice: [javascript.md](javascript.md#testing).

A CI whose only gate is `vitest run` needs a `tsc --noEmit` step over a tsconfig that includes the test files. Type assertions do nothing at runtime; they fail only when a type checker reads the file: `tsc`, `vitest --typecheck` (which checks `*.test-d.ts` files by default), or `tsd`.

```typescript
import { expectTypeOf, it } from 'vitest';

it('infers the element type', () => {
  expectTypeOf(getFirst([1, 2, 3])).toEqualTypeOf<number | undefined>();
  expectTypeOf(getFirst(['a'])).not.toEqualTypeOf<number | undefined>();
  // @ts-expect-error: a correct negative test; it fails once the call starts to type-check
  expectTypeOf(getFirst(['a'])).toEqualTypeOf<number>();
});
```

---

## Path Aliases and Module Resolution

`paths` only tells the type checker where modules live: the bundler (Vite or webpack `resolve.alias`), the test runner, and the runtime must resolve the same specifiers, and a published package ships the aliases unresolved unless the build rewrites them (for example with tsc-alias). Node.js ignores `paths`, including under type stripping; code it runs without a bundler uses `package.json` subpath imports (`"imports"`, specifiers starting with `#`), which TypeScript understands under `moduleResolution` `nodenext` or `bundler` ([nodejs.md](nodejs.md#modules--packaging)).

`baseUrl` is deprecated in TS 6.0 (an error unless `"ignoreDeprecations": "6.0"` is set) and rejected by TS 7.0; it is valid on TS 5.x, so flag it only on TS 6+ or before a TS 7 move. Without it, `paths` targets resolve relative to the tsconfig file:

```jsonc
// ✅ TS 6+: no baseUrl; "./src/*" resolves relative to tsconfig.json
{ "compilerOptions": { "paths": { "@/*": ["./src/*"] } } }
```

---

## Modern TypeScript Features

### Decorators: Stage 3 and legacy

Since TS 5.0, decorators without a flag follow the TC39 Stage 3 proposal: they receive a `context` object, cannot decorate parameters, and do not work with `emitDecoratorMetadata`. With `experimentalDecorators` on, every decorator in the project uses the legacy signature. Frameworks that use parameter decorators or read emitted metadata need the legacy model: NestJS resolves constructor dependencies from `emitDecoratorMetadata`, and `@Inject()` and `@Body()` are parameter decorators. Flag legacy decorators only in code with no such dependency; a Stage 3 method decorator has the signature `(target, context: ClassMethodDecoratorContext) => replacement`.

### `using` declarations (explicit resource management, TS 5.2+)

`using` calls `[Symbol.dispose]()` when the scope exits, including through a throw, and `await using` awaits `[Symbol.asyncDispose]()`, so they replace `try`/`finally` cleanup.

```typescript
import { mkdtempDisposableSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

// ✅ A unique, private temporary directory (Node.js 24.4+), removed however the function exits;
//    a hand-built `/tmp/file-${Date.now()}` path is predictable and open to races
function exportReport(rows: readonly string[]): void {
  using dir = mkdtempDisposableSync(join(tmpdir(), 'report-'));
  const file = join(dir.path, 'report.csv');
  writeFileSync(file, rows.join('\n'));
  upload(file);
}
```

`fsPromises.mkdtempDisposable()` is the `await using` counterpart.

### Use `erasableSyntaxOnly` when Node.js runs the `.ts` files (TS 5.8+)

Node.js type stripping deletes the types and runs what is left, so syntax that generates JavaScript fails when the file loads ([runtime rules](nodejs.md#runtime-versions--built-ins)). `erasableSyntaxOnly` makes `tsc` reject it; Node.js recommends it together with `verbatimModuleSyntax` (type-only imports written as `import type`).

```typescript
// tsconfig.json: "erasableSyntaxOnly": true, "verbatimModuleSyntax": true, "rewriteRelativeImportExtensions": true

// ❌ Each of these fails under type stripping; with the flags, tsc reports it
import { User } from './user.ts';                        // User is only a type
enum Status { Active = 'active', Archived = 'archived' } // an enum emits an object
class UserService {
  constructor(private readonly repo: UserRepository) {}  // a parameter property
}

// ✅ Erasable equivalents
import type { User } from './user.ts';
const Status = { Active: 'active', Archived: 'archived' } as const;
type Status = (typeof Status)[keyof typeof Status];
class UserService {
  private readonly repo: UserRepository;
  constructor(repo: UserRepository) {
    this.repo = repo;
  }
}
```

Node.js also fails on decorators, which `erasableSyntaxOnly` does not report. NestJS relies on parameter properties and legacy decorators and is compiled by `tsc` or SWC, so do not ask for these flags there.

### Review TypeScript 6.0 default changes when upgrading

| Option | New default | What to check |
| --- | --- | --- |
| `strict` | `true` | New errors in code that compiled non-strict; `"strict": false` needs a reason |
| `types` | `[]` | Globals such as `process` or `describe` disappear until listed, for example `"types": ["node", "vitest/globals"]` |
| `rootDir` | The tsconfig directory | Output moves (for example to `dist/src/`) where the root used to be inferred; set `"rootDir": "./src"` |
| `module`, `target` | `esnext`, and the newest ES version (`es2025`; it floats) | Pin both for published packages and for runtimes that lag behind |
| `noUncheckedSideEffectImports` | `true` | Unresolved side-effect imports are errors, including `import './styles.css'` without a `declare module '*.css' {}` |
| `esModuleInterop`, `allowSyntheticDefaultImports` | always `true` | `false` is deprecated |

Options deprecated in 6.0 are errors unless `"ignoreDeprecations": "6.0"` is set, and TS 7.0 rejects them: `target: es5`, `downlevelIteration`, `moduleResolution: node` (`node10`) and `classic`, `module: amd`/`umd`/`systemjs`/`none`, `baseUrl`, `outFile`, `esModuleInterop: false`, `allowSyntheticDefaultImports: false`, `alwaysStrict: false`, the `module Foo {}` namespace syntax, and `asserts` on imports (use `with`).

### Check tooling before upgrading to TypeScript 7

TS 7.0 (2026-07-08) is the native Go port: the same `typescript` package and `tsc` command, about 10x faster full builds, and no programmatic API (7.1 is expected to add a new one). Every tool that imports `typescript` as a library still needs the 6.0 API: typescript-eslint, `nest build` and its Swagger and GraphQL plugins, ts-jest, ts-loader, ts-node, and the Vue, Svelte, Astro, Angular, and MDX tooling. The TS 7.0 announcement documents a side-by-side install:

```json
{
  "devDependencies": {
    "@typescript/native": "npm:typescript@^7.0.2",
    "typescript": "npm:@typescript/typescript6@^6.0.2"
  }
}
```

TS 7 also drops several JSDoc constructs in JavaScript checking ([javascript.md](javascript.md#linting--tooling)).

---

## References

- [TypeScript Handbook](https://www.typescriptlang.org/docs/handbook/intro.html)
- [TSConfig Reference](https://www.typescriptlang.org/tsconfig/)
- [TypeScript 6.0 release notes](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-6-0.html)
- [Announcing TypeScript 7.0](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/)
- [typescript-eslint: Typed Linting](https://typescript-eslint.io/getting-started/typed-linting/)
