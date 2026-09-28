# TypeScript Code Review Guide

Review guidance for TypeScript's type system: type safety, generics, advanced types, strict configuration, immutability, typed linting, type tests, module resolution, and modern TypeScript features (4.9 through 7.0).

> **Load [javascript.md](javascript.md) too.** TypeScript compiles to JavaScript, so runtime semantics, async and Promise pitfalls, modules, DOM safety, and testing are covered there; this guide covers what the type system adds. For Node.js services also load [nodejs.md](nodejs.md); for NestJS, [nestjs.md](nestjs.md).

## Table of Contents

- [Type Safety Basics](#type-safety-basics)
- [Generic Patterns](#generic-patterns)
- [Advanced Types](#advanced-types)
- [Strict Mode Configuration](#strict-mode-configuration)
- [Immutability](#immutability)
- [ESLint Rules](#eslint-rules)
- [Testing TypeScript](#testing-typescript)
- [Path Aliases and Module Resolution](#path-aliases-and-module-resolution)
- [Modern TypeScript Features](#modern-typescript-features)
- [Review Checklist](#review-checklist)
- [References](#references)

---

## Type Safety Basics

### Avoid `any`

`any` turns off checking for every value it touches, and values derived from it are `any` as well. Use a real type, or `unknown` plus a type guard when the shape is only known at runtime.

```typescript
// ❌ Using any defeats type safety
function processData(data: any) {
  return data.value;  // No type checking; can crash at runtime
}

// ✅ Use proper types
interface DataPayload {
  value: string;
}
function processData(data: DataPayload) {
  return data.value;
}

// ✅ For values of unknown type, use unknown + a type guard
function processUnknown(data: unknown) {
  if (typeof data === 'object' && data !== null && 'value' in data && typeof data.value === 'string') {
    return data.value;  // Narrowed to string by the checks, no cast needed
  }
  throw new Error('Invalid data');
}
```

### Type narrowing

An `as` assertion only silences the compiler; it checks nothing at runtime. Narrow the type with `Array.isArray`, `typeof`, `instanceof`, `in`, or a discriminant property instead.

```typescript
// ❌ Unsafe type assertion
function getLength(value: string | string[]) {
  return (value as string[]).length;  // Wrong when value is a string
}

// ✅ Use a type guard
function getLength(value: string | string[]): number {
  if (Array.isArray(value)) {
    return value.length;
  }
  return value.length;
}

// ✅ Use the in operator
interface Dog { bark(): void }
interface Cat { meow(): void }

function speak(animal: Dog | Cat) {
  if ('bark' in animal) {
    animal.bark();
  } else {
    animal.meow();
  }
}
```

### Literal types and `as const`

Properties of an object literal widen to `string` or `number`, so they no longer fit a parameter typed as a literal union. `as const` keeps the literal types and makes the object readonly.

```typescript
// ❌ Type is too wide
const config = {
  endpoint: '/api',
  method: 'GET'  // Type is string
};

// ✅ Use as const to get literal types
const config = {
  endpoint: '/api',
  method: 'GET'
} as const;  // method's type is 'GET'

// ✅ Works with function parameters
function request(method: 'GET' | 'POST', url: string) { ... }
request(config.method, config.endpoint);  // OK
```

---

## Generic Patterns

### Basic generics

Functions that differ only in the element type belong in one generic function, which keeps the caller's type instead of widening it.

```typescript
// ❌ Duplicated code
function getFirstString(arr: string[]): string | undefined {
  return arr[0];
}
function getFirstNumber(arr: number[]): number | undefined {
  return arr[0];
}

// ✅ Use a generic
function getFirst<T>(arr: T[]): T | undefined {
  return arr[0];
}
```

### Generic constraints

An unconstrained type parameter tells the compiler nothing, so the function body cannot use its properties. A constraint such as `K extends keyof T` lets the compiler check call sites and infer exact return types.

```typescript
// ❌ Unconstrained generic: properties cannot be accessed
function getProperty<T>(obj: T, key: string) {
  return obj[key];  // Error: cannot index
}

// ✅ Constrain with keyof
function getProperty<T, K extends keyof T>(obj: T, key: K): T[K] {
  return obj[key];
}

const user = { name: 'Alice', age: 30 };
getProperty(user, 'name');  // Return type is string
getProperty(user, 'age');   // Return type is number
getProperty(user, 'foo');   // Error: 'foo' is not in keyof User
```

### Generic defaults

A default type argument keeps the common case short and still allows a precise type when the caller has one.

```typescript
// ✅ Provide a sensible default type
interface ApiResponse<T = unknown> {
  data: T;
  status: number;
  message: string;
}

// The type argument can be omitted
const response: ApiResponse = { data: null, status: 200, message: 'OK' };
// or given explicitly
const userResponse: ApiResponse<User> = { ... };
```

### Common generic utility types

Derive related types from one source type with the built-in utility types. Hand-copied field lists drift when the source type changes.

```typescript
// ✅ Use the built-in utility types
interface User {
  id: number;
  name: string;
  email: string;
}

type PartialUser = Partial<User>;         // All properties optional
type RequiredUser = Required<User>;       // All properties required
type ReadonlyUser = Readonly<User>;       // All properties readonly
type UserKeys = keyof User;               // 'id' | 'name' | 'email'
type NameOnly = Pick<User, 'name'>;       // { name: string }
type WithoutId = Omit<User, 'id'>;        // { name: string; email: string }
type UserRecord = Record<string, User>;   // { [key: string]: User }
```

---

## Advanced Types

### Conditional types

Conditional types compute one type from another. When the checked type is a bare type parameter they distribute over unions (`IsString<string | number>` is `boolean`); wrap both sides in brackets, `[T] extends [string]`, when that is not wanted.

```typescript
// ✅ Return different types depending on the input type
type IsString<T> = T extends string ? true : false;

type A = IsString<string>;  // true
type B = IsString<number>;  // false

// ✅ Extract the array element type
type ElementType<T> = T extends (infer U)[] ? U : never;

type Elem = ElementType<string[]>;  // string

// ✅ Extract a function's return type (built in as ReturnType)
type MyReturnType<T> = T extends (...args: any[]) => infer R ? R : never;
```

### Mapped types

Mapped types transform every property of a type in one place; key remapping with `as` renames or filters the keys.

```typescript
// ✅ Transform every property of an object type
type Nullable<T> = {
  [K in keyof T]: T[K] | null;
};

interface User {
  name: string;
  age: number;
}

type NullableUser = Nullable<User>;
// { name: string | null; age: number | null }

// ✅ Add a prefix
type Getters<T> = {
  [K in keyof T as `get${Capitalize<string & K>}`]: () => T[K];
};

type UserGetters = Getters<User>;
// { getName: () => string; getAge: () => number }
```

### Template literal types

Template literal types turn string conventions, such as event names or route prefixes, into checked types.

```typescript
// ✅ Type-safe event names
type EventName = 'click' | 'focus' | 'blur';
type HandlerName = `on${Capitalize<EventName>}`;
// 'onClick' | 'onFocus' | 'onBlur'

// ✅ API route type
type ApiRoute = `/api/${string}`;
const route: ApiRoute = '/api/users';  // OK
const badRoute: ApiRoute = '/users';   // Error
```

### Discriminated unions

Model states that carry different data as a union with a literal discriminant. Checking the discriminant narrows the type, and impossible combinations, such as `success: true` together with an `error`, cannot be built.

```typescript
// ✅ Use a discriminant property for type safety
type Result<T, E> =
  | { success: true; data: T }
  | { success: false; error: E };

function handleResult(result: Result<User, Error>) {
  if (result.success) {
    console.log(result.data.name);  // TypeScript knows data exists
  } else {
    console.log(result.error.message);  // TypeScript knows error exists
  }
}

// ✅ Action/reducer pattern
type Action =
  | { type: 'INCREMENT'; payload: number }
  | { type: 'DECREMENT'; payload: number }
  | { type: 'RESET' };

function reducer(state: number, action: Action): number {
  switch (action.type) {
    case 'INCREMENT':
      return state + action.payload;  // payload type is known
    case 'DECREMENT':
      return state - action.payload;
    case 'RESET':
      return 0;  // No payload here
  }
}
```

### Make switches over unions exhaustive

The reducer above is safe because of its return type: if a new `Action` member is not handled, the function "lacks ending return statement" (TS2366) and fails to compile. A `void` function gets no such error, so it needs a `never` check in the `default` branch, or the typed rule `@typescript-eslint/switch-exhaustiveness-check`, which is not part of the recommended or strict configs.

```typescript
// ✅ Without the RESET case, the assignment to never fails to compile
function logAction(action: Action): void {
  switch (action.type) {
    case 'INCREMENT':
    case 'DECREMENT':
      console.log(action.type, action.payload);
      break;
    case 'RESET':
      console.log(action.type);
      break;
    default: {
      const unhandled: never = action;
      throw new Error(`Unhandled action: ${JSON.stringify(unhandled)}`);
    }
  }
}
```

---

## Strict Mode Configuration

### Recommended tsconfig.json

`strict` enables the whole family of strict checks and is the default from TS 6.0; the additional options catch bugs that `strict` leaves alone. A PR that turns any of them off needs a stated reason.

```json
{
  "compilerOptions": {
    // ✅ Strict options that must be on
    "strict": true,
    "noImplicitAny": true,
    "strictNullChecks": true,
    "strictFunctionTypes": true,
    "strictBindCallApply": true,
    "strictPropertyInitialization": true,
    "noImplicitThis": true,
    "useUnknownInCatchVariables": true,

    // ✅ Additional recommended options
    "noUncheckedIndexedAccess": true,
    "noImplicitReturns": true,
    "noFallthroughCasesInSwitch": true,
    "exactOptionalPropertyTypes": true,
    "noPropertyAccessFromIndexSignature": true
  }
}
```

NestJS projects often set `"strictPropertyInitialization": false` (the NestJS starter does), because the framework populates DTO and entity properties. Accept that there, and keep the other strict options on.

### What `noUncheckedIndexedAccess` changes

With this option, indexing an array or a record yields `T | undefined`, which is what a missing index or key returns at runtime. It is not part of `strict` and has to be enabled on its own.

```typescript
// tsconfig: "noUncheckedIndexedAccess": true

const arr = [1, 2, 3];
const first = arr[0];  // Type is number | undefined

// ❌ Using it directly can fail
console.log(first.toFixed(2));  // Error: may be undefined

// ✅ Check first
if (first !== undefined) {
  console.log(first.toFixed(2));
}

// ✅ Or use a non-null assertion (only when you are certain)
console.log(arr[0]!.toFixed(2));
```

---

## Immutability

### `Readonly` and `ReadonlyArray`

A `readonly` parameter documents that the function leaves its input alone, and the compiler rejects mutation inside the function.

```typescript
// ❌ A mutable parameter can be modified by accident
function processUsers(users: User[]) {
  users.sort((a, b) => a.name.localeCompare(b.name));  // Mutates the caller's array!
  return users;
}

// ✅ Use readonly to prevent modification
function processUsers(users: readonly User[]): User[] {
  return [...users].sort((a, b) => a.name.localeCompare(b.name));
}

// ✅ Deep readonly
type DeepReadonly<T> = {
  readonly [K in keyof T]: T[K] extends object ? DeepReadonly<T[K]> : T[K];
};
```

### Immutable function parameters

A `readonly` array constraint lets callers pass `as const` tuples, so the literal values survive into the return type.

```typescript
// ✅ Protect data with as const and readonly
function createConfig<T extends readonly string[]>(routes: T) {
  return routes;
}

const routes = createConfig(['home', 'about', 'contact'] as const);
// Type is readonly ['home', 'about', 'contact']
```

> 📖 `readonly` is checked at compile time only. Runtime copying (spread vs `structuredClone`, `toSorted()` and the other copying array methods, shallow `Object.freeze`) is covered in [javascript.md](javascript.md#mutation-and-copying).

---

## ESLint Rules

### Recommended @typescript-eslint rules

The type-checked configs run rules that need type information from the compiler (enabled here with `projectService`); only those rules can see unsafe `any` flows and unhandled promises. The config uses ESLint's `defineConfig()` (ESLint 9.22+), which replaces the deprecated `tseslint.config()`.

```javascript
// eslint.config.js (flat config; defineConfig needs ESLint 9.22+; typescript-eslint v8)
import eslint from '@eslint/js';
import { defineConfig } from 'eslint/config';
import tseslint from 'typescript-eslint';

export default defineConfig(
  eslint.configs.recommended,
  // Rule sets that need type information; they replace the old recommended-requiring-type-checking
  tseslint.configs.recommendedTypeChecked,
  tseslint.configs.strictTypeChecked,
  {
    languageOptions: {
      parserOptions: {
        // Lets the typed rules find the matching tsconfig automatically
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      // ✅ Type safety
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unsafe-assignment': 'error',
      '@typescript-eslint/no-unsafe-member-access': 'error',
      '@typescript-eslint/no-unsafe-call': 'error',
      '@typescript-eslint/no-unsafe-return': 'error',

      // ✅ Best practices
      '@typescript-eslint/explicit-function-return-type': 'warn',
      '@typescript-eslint/no-floating-promises': 'error',
      '@typescript-eslint/await-thenable': 'error',
      '@typescript-eslint/no-misused-promises': 'error',

      // ✅ Code style
      '@typescript-eslint/consistent-type-imports': 'error',
      '@typescript-eslint/prefer-nullish-coalescing': 'error',
      '@typescript-eslint/prefer-optional-chain': 'error',
    },
  },
);
```

⚠️ typescript-eslint v8 supports TypeScript `>=4.8.4 <6.1.0`, and TypeScript 7.0 ships no compiler API. A TS 7 project that lints with type information has to keep the 6.0 API installed for the linter; see [Check tooling before upgrading to TypeScript 7](#check-tooling-before-upgrading-to-typescript-7).

### Typed rules that catch async bugs

These rules know which expressions are promises, so they catch promise misuse that plain ESLint cannot see. All three are in `recommendedTypeChecked`; the runtime behavior behind them is explained in [javascript.md](javascript.md#no-floating-promises).

| Rule | Reports |
|---|---|
| `@typescript-eslint/no-floating-promises` | A promise that is not awaited, returned, or given a rejection handler |
| `@typescript-eslint/no-misused-promises` | A promise where a `void` callback or a condition is expected: `items.forEach(async ...)`, or `if (isAllowed())` with an async `isAllowed` |
| `@typescript-eslint/await-thenable` | `await` on a value that is not a promise, usually a sync function mistaken for an async one |

Treat an `eslint-disable` for these rules, or a `void` added only to silence one, as a finding unless a comment explains it.

---

## Testing TypeScript

### Running tests on TypeScript sources

Most test setups strip types without checking them: Vitest, `ts-jest` in isolated-modules (transpile-only) mode, and Node.js type stripping (see [nodejs.md](nodejs.md#runtime-versions--built-ins)) all run code that `tsc` would reject. A green test run says nothing about type errors, so CI needs its own type-check over a tsconfig that includes the test files. Runner choice and general test practice are in [javascript.md](javascript.md#testing).

```json
// ❌ package.json: the only gate is a runner that strips types without checking them
"scripts": {
  "test": "vitest run"
}

// ✅ Type-check everything, tests included, then run the tests
"scripts": {
  "typecheck": "tsc --noEmit",
  "test": "vitest run",
  "ci": "npm run typecheck && npm test"
}
```

### Type tests (tsd / expect-type)

Libraries and shared utilities whose value is in their types (generics, overloads, inference) need tests for those types. Type assertions do nothing at runtime; they fail only when a type checker reads the file: `tsc`, `vitest --typecheck` (which checks `*.test-d.ts` files by default), or `tsd`.

```typescript
// ✅ Verify type inference with expect-type
import { expectTypeOf } from 'vitest';

function getFirst<T>(arr: T[]): T | undefined {
  return arr[0];
}

it('should infer correct return type', () => {
  const result = getFirst([1, 2, 3]);
  expectTypeOf(result).toEqualTypeOf<number | undefined>();
});

// ✅ Verify function signatures with expect-type
const fn = (a: string, b: number) => a.repeat(b);
expectTypeOf(fn).parameters.toEqualTypeOf<[string, number]>();
expectTypeOf(fn).returns.toBeString();

// ❌ A type error is caught at compile time
const result = getFirst(['a', 'b']);
// @ts-expect-error: type mismatch
expectTypeOf(result).toEqualTypeOf<number>();
```

---

## Path Aliases and Module Resolution

### tsconfig paths and path aliases

Aliases replace deep relative imports, but `paths` only tells the type checker where modules live; the bundler, test runner, or runtime has to resolve the same specifiers. `baseUrl` is deprecated in TS 6.0 (an error unless `"ignoreDeprecations": "6.0"` is set) and rejected by TS 7.0; `paths` entries resolve relative to the tsconfig file without it.

```json
// ❌ tsconfig.json with baseUrl: deprecated in TS 6.0, an error in TS 7.0
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"],
      "@components/*": ["./src/components/*"],
      "@utils/*": ["./src/utils/*"]
    }
  }
}

// ✅ Same file without the "baseUrl" line: the "./src/..." targets resolve relative to tsconfig.json
```

```typescript
// ❌ Before aliases: deep relative paths
import { Button } from '../../components/ui/Button';
import { formatDate } from '../../../utils/date';

// ✅ With aliases: clear, and less likely to break when files move
import { Button } from '@components/ui/Button';
import { formatDate } from '@utils/date';
```

```typescript
// ⚠️ tsconfig paths only affect TypeScript compilation, not the runtime
// Pair them with the bundler's alias resolution (Vite, webpack) or with tsx

// vite.config.ts
import { resolve } from 'node:path';

export default defineConfig({
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
});

// ⚠️ When you publish an npm package, tsconfig paths are not resolved automatically
// Handle them with tsc-alias or tsconfig-paths
```

Node.js ignores `paths`, including when it runs `.ts` files through type stripping. For code that Node.js runs without a bundler, prefer `package.json` subpath imports (`"imports"`, specifiers starting with `#`): Node.js resolves them at runtime, and TypeScript understands them under `moduleResolution` `nodenext` or `bundler`. Library `exports` maps and dual ESM/CommonJS packaging are covered in [nodejs.md](nodejs.md#modules--packaging).

---

## Modern TypeScript Features

### The `satisfies` keyword (TS 4.9+)

`satisfies` checks a value against a type without replacing the value's inferred type, so literal types and exact keys survive while a wrong shape is still an error. An annotation such as `const palette: Record<string, string>` widens the value to the annotated type instead.

```typescript
// ❌ Without satisfies: the type is too wide
const palette = {
  red: '#ff0000',
  green: '#00ff00',
  blue: '#0000ff',
};
// palette.red is typed string; the exact '#ff0000' value is lost

// ✅ satisfies keeps the literal types and still validates the shape
const palette = {
  red: '#ff0000',
  green: '#00ff00',
  blue: '#0000ff',
} satisfies Record<string, `#${string}`>;

// palette.red is typed '#ff0000' (not string)
// but new properties are still checked against the format
```

```typescript
// ✅ satisfies to check that an object matches an interface
interface UserConfig {
  theme: 'light' | 'dark';
  locale: string;
}

const config = {
  theme: 'dark',
  locale: 'en-US',
} satisfies UserConfig;
// config.theme is typed 'dark' (not 'light' | 'dark')
// every property is type-checked by satisfies
```

### `const` type parameters (TS 5.0+)

A `const` type parameter infers literal, readonly types from the argument, so callers do not have to add `as const`. Array arguments keep their tuple type only when the constraint is a `readonly` array.

```typescript
// ❌ Before: callers needed an as const assertion
function getRoutes<T extends readonly string[]>(routes: T) {
  return routes;
}
const routes = getRoutes(['home', 'about'] as const);

// ✅ TS 5.0+: const type parameter
function getRoutes<const T extends readonly string[]>(routes: T) {
  return routes;
}
const routes = getRoutes(['home', 'about']);
// routes is typed readonly ['home', 'about']
```

```typescript
// ✅ Real-world case: a type-safe config object
declare function createConfig<const T extends Record<string, unknown>>(
  config: T
): T;

const config = createConfig({
  api: { url: 'https://api.example.com', version: 2 },
  features: { newDashboard: true },
});
// config.api.url is typed 'https://api.example.com' (a literal)
```

### Decorators (Stage 3, TS 5.0+)

TS 5.0 implements the TC39 decorators proposal (Stage 3). These decorators need no compiler flag and receive a `context` object that describes what they decorate. They are a different API from legacy `experimentalDecorators`: they cannot decorate parameters and do not work with `emitDecoratorMetadata`.

```typescript
// ✅ Stage 3 decorators (TS 5.0+, experimentalDecorators no longer needed)
function logged<This, Args extends unknown[], Return>(
  target: (this: This, ...args: Args) => Return,
  context: ClassMethodDecoratorContext
) {
  return function (this: This, ...args: Args): Return {
    console.log(`Calling ${String(context.name)} with`, args);
    return target.apply(this, args);
  };
}

class Calculator {
  @logged
  add(a: number, b: number): number {
    return a + b;
  }
}

// Output: Calling add with [1, 2]
new Calculator().add(1, 2);
```

```typescript
// ⚠️ Stage 3 decorators differ from the legacy experimentalDecorators
// Legacy: requires "experimentalDecorators": true in tsconfig
// New (TS 5.0+): supported by default, no extra configuration

// ❌ Legacy decorator signature (still supported, but legacy)
function deprecated<T extends { new (...args: any[]): {} }>(constructor: T) {
  return class extends constructor { /* ... */ };
}

// ✅ New decorators receive a context that says what they decorate
function sealed<T extends { new (...args: any[]): {} }>(
  target: T,
  context: ClassDecoratorContext
) {
  // context.kind === 'class'
}
```

Do not flag `experimentalDecorators` in NestJS code. Nest resolves constructor dependencies from the metadata that `emitDecoratorMetadata` emits, and `@Inject()` and `@Body()` are parameter decorators; both exist only in legacy mode, and the NestJS starter tsconfig enables `experimentalDecorators` and `emitDecoratorMetadata`. The ❌ above applies to new decorators in code without such a framework dependency.

### `using` declarations (explicit resource management, TS 5.2+)

`using` calls `[Symbol.dispose]()` when the enclosing scope exits, including through a thrown error, so it replaces `try`/`finally` cleanup. The compiler needs the `esnext` or `esnext.disposable` lib, and the runtime needs `Symbol.dispose` and `Symbol.asyncDispose` (or a polyfill); Node.js 24 runs `using` natively.

```typescript
// ✅ Implement Symbol.dispose for automatic cleanup
class TempFile implements Disposable {
  private path: string;

  constructor() {
    this.path = `/tmp/file-${Date.now()}`;
  }

  write(data: string) { /* ... */ }

  [Symbol.dispose]() {
    // Automatic cleanup, however the function exits (normally or by throwing)
    fs.unlinkSync(this.path);
    console.log(`Cleaned up: ${this.path}`);
  }
}

function processFile() {
  using file = new TempFile(); // using declaration
  file.write('data');
  // file[Symbol.dispose]() is called automatically when the scope ends
}
```

```typescript
// ✅ AsyncDisposable for async resources (TS 5.2+)
class DatabaseConnection implements AsyncDisposable {
  private constructor(private readonly db: sqlite3.Database) {}

  // Async factory: callers only get a connection whose open callback succeeded
  static open(filename: string): Promise<DatabaseConnection> {
    return new Promise((resolve, reject) => {
      const db = new sqlite3.Database(filename, (err) => {
        if (err) reject(err);
        else resolve(new DatabaseConnection(db));
      });
    });
  }

  async [Symbol.asyncDispose]() {
    // close() takes a callback and returns void: wrap it in a Promise to await it
    await new Promise<void>((resolve, reject) => {
      this.db.close((err) => {
        if (err) reject(err);
        else resolve();
      });
    });
  }
}

async function query() {
  await using conn = await DatabaseConnection.open(':memory:'); // await using
  // ... run queries with conn
  // await conn[Symbol.asyncDispose]() runs automatically when the scope ends
}
```

### Enum improvements (TS 5.0+)

Since TS 5.0 every enum is a union enum, so enum members can be narrowed and used as types. Enums still emit a runtime object, which matters when Node.js strips types (next rule).

```typescript
// ✅ All enums are now union enums (TS 5.0+)
enum Color {
  Red = 'RED',
  Green = 'GREEN',
}

// Before: Color behaved inconsistently when used as a type
// Now: Color is the union of its members (Color.Red | Color.Green)
const color: Color = Color.Red; // TypeScript now infers the Color type better
```

### Use `erasableSyntaxOnly` when Node.js runs the `.ts` files (TS 5.8+)

Node.js type stripping ([nodejs.md](nodejs.md#runtime-versions--built-ins)) deletes the types and runs what is left, so TypeScript syntax that generates JavaScript fails when the file loads. `erasableSyntaxOnly` makes `tsc` reject that syntax at compile time; Node.js recommends it together with `verbatimModuleSyntax`, which requires type-only imports to be written as `import type`.

```typescript
// tsconfig.json: "erasableSyntaxOnly": true, "verbatimModuleSyntax": true

// ❌ Each of these fails under type stripping; with these flags tsc reports it
import { User } from './user.ts';                          // User is only a type
enum Status { Active = 'active', Archived = 'archived' }   // enum emits an object
class UserService {
  constructor(private readonly repo: UserRepository) {}    // parameter property
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

Node.js also fails on decorators, which `erasableSyntaxOnly` does not report. NestJS code relies on parameter properties and legacy decorators and is compiled by `tsc` or SWC, so do not ask for this flag there.

### Review TypeScript 6.0 default changes when upgrading

TS 6.0 changed several defaults, so a version bump alone can change what compiles, which global types exist, and where the output lands. Check that the PR spells out the options the project relied on.

| Option | New default | What to check |
|---|---|---|
| `strict` | `true` | New errors in code that compiled in non-strict mode; `"strict": false` needs a reason |
| `types` | `[]` | Globals such as `process` or `describe` disappear until listed, for example `"types": ["node", "vitest/globals"]` |
| `rootDir` | The tsconfig directory | Output moves (for example to `dist/src/`) where the root used to be inferred; set `"rootDir": "./src"` |
| `module`, `target` | `esnext`, the newest ES version (`es2025` today; it floats) | Pin both for published packages and for runtimes that lag behind |
| `noUncheckedSideEffectImports` | `true` | Unresolved side-effect imports are errors, including `import './styles.css'` without a `declare module '*.css' {}` |

Options deprecated in 6.0 are errors unless `"ignoreDeprecations": "6.0"` is set, and TS 7.0 rejects them outright: `target: es5`, `downlevelIteration`, `moduleResolution: node` (`node10`) and `classic`, `module: amd`/`umd`/`systemjs`/`none`, `baseUrl`, `outFile`, `esModuleInterop: false`, `allowSyntheticDefaultImports: false`, `alwaysStrict: false`, the `module Foo {}` namespace syntax, and `asserts` on imports (use `with`). Accept `ignoreDeprecations` only as a temporary step with a follow-up.

### Check tooling before upgrading to TypeScript 7

TS 7.0 (July 2026) is the native Go port of the compiler. It keeps the `typescript` package name and the `tsc` command and is about 10x faster on full builds, but it ships no programmatic API until 7.1. Tools that import `typescript` as a library, typescript-eslint among them, still need the 6.0 API, and every option deprecated in 6.0 is a hard error. The TS 7.0 announcement documents a side-by-side install:

```json
// package.json: tsc runs TS 7; tools that import "typescript" get the 6.0 API
{
  "devDependencies": {
    "@typescript/native": "npm:typescript@^7.0.2",
    "typescript": "npm:@typescript/typescript6@^6.0.2"
  }
}
```

---

## Review Checklist

### Type system
- [ ] No `any` (use `unknown` plus type guards instead)
- [ ] Interfaces and types are complete and meaningfully named
- [ ] Generics are used to improve reuse
- [ ] Union types are correctly narrowed
- [ ] Utility types (`Partial`, `Pick`, `Omit`, etc.) are used where they fit
- [ ] Switches over unions are exhaustive (`never` check or `switch-exhaustiveness-check`)

### Generics
- [ ] Generics have appropriate constraints (`extends`)
- [ ] Generic parameters have sensible defaults
- [ ] No over-generic code (KISS)

### Strict mode
- [ ] `tsconfig.json` enables `strict: true`
- [ ] `noUncheckedIndexedAccess` is enabled
- [ ] No `@ts-ignore` (use `@ts-expect-error` instead)
- [ ] A TS 6.0+ upgrade sets `types` and `rootDir` explicitly and removes deprecated options instead of relying on `ignoreDeprecations`

### Immutability
- [ ] Function parameters are not mutated directly
- [ ] New objects and arrays are created with the spread operator
- [ ] `readonly` modifiers are considered

### ESLint
- [ ] The `@typescript-eslint` recommended rules are enabled (type-checked configs for typed rules)
- [ ] `@typescript-eslint/no-floating-promises` and `@typescript-eslint/no-misused-promises` are enabled
- [ ] No ESLint warnings or errors
- [ ] `consistent-type-imports` is used
- [ ] A TS 7 project keeps the 6.0 API installed for typed linting

### Testing & modules
- [ ] CI runs `tsc --noEmit` over sources and tests; the test runner alone does not check types
- [ ] Type tests (`expectTypeOf`, tsd) run under a type checker
- [ ] Path aliases also resolve at runtime (bundler alias, tsconfig-paths, or `package.json` `imports`)
- [ ] Code that Node.js runs through type stripping enables `erasableSyntaxOnly` and `verbatimModuleSyntax`
- [ ] The [javascript.md](javascript.md#review-checklist) checklist is applied to the runtime behavior

---

## References

- [TypeScript Handbook](https://www.typescriptlang.org/docs/handbook/intro.html)
- [Narrowing (TypeScript Handbook)](https://www.typescriptlang.org/docs/handbook/2/narrowing.html)
- [Conditional Types (TypeScript Handbook)](https://www.typescriptlang.org/docs/handbook/2/conditional-types.html)
- [Utility Types (TypeScript Handbook)](https://www.typescriptlang.org/docs/handbook/utility-types.html)
- [Modules Reference (TypeScript Handbook)](https://www.typescriptlang.org/docs/handbook/modules/reference.html)
- [TSConfig Reference](https://www.typescriptlang.org/tsconfig/): [`strict`](https://www.typescriptlang.org/tsconfig/#strict), [`noUncheckedIndexedAccess`](https://www.typescriptlang.org/tsconfig/#noUncheckedIndexedAccess), [`erasableSyntaxOnly`](https://www.typescriptlang.org/tsconfig/#erasableSyntaxOnly), [`verbatimModuleSyntax`](https://www.typescriptlang.org/tsconfig/#verbatimModuleSyntax)
- TypeScript release notes: [4.9](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-4-9.html), [5.0](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-0.html), [5.2](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-2.html), [5.8](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-8.html), [6.0](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-6-0.html)
- [Announcing TypeScript 7.0 (TypeScript blog)](https://devblogs.microsoft.com/typescript/announcing-typescript-7-0/)
- [typescript-eslint: Getting Started](https://typescript-eslint.io/getting-started/) and [Typed Linting](https://typescript-eslint.io/getting-started/typed-linting/)
- [typescript-eslint: Rules](https://typescript-eslint.io/rules/)
- [typescript-eslint: Dependency Versions](https://typescript-eslint.io/users/dependency-versions/)
- [ESLint: Configuration Files](https://eslint.org/docs/latest/use/configure/configuration-files)
- [Vitest: Testing Types](https://vitest.dev/guide/testing-types)
- [tsd](https://github.com/tsdjs/tsd)
- [expect-type](https://github.com/mmkal/expect-type)
- [Node.js: Modules: TypeScript](https://nodejs.org/api/typescript.html)
