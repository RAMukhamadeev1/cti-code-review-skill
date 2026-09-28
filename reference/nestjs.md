# NestJS Code Review Guide

NestJS 11 and 12 applications: validation (class-validator DTOs or Standard Schema), guards and interceptors, exception filters, dependency injection and scopes, modules, lifecycle, testing, and house layering conventions.

Load with [typescript.md](typescript.md); open [nodejs.md](nodejs.md) only for runtime topics (bootstrap, shutdown, streams, configuration), and [javascript.md](javascript.md) sections for language semantics.

## Review Checklist

Read this checklist first; open a section only when the diff contains its pattern.

Default severities: 🔴 [blocking] · 🟡 [important] · 🟢 [nit] · 💡 [suggestion]; adjust them to the impact in context. A rule a linter or tsconfig already enforces is a finding only when the diff disables it, pre-existing code only when the change makes it worse, and house conventions only when the repository already follows them.

### Validation → [Validation Patterns (DTO)](#validation-patterns-dto)

- [ ] 🔴 New or changed endpoints validate body, query, and params through the app's global mechanism: `ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true })` for class-validator DTOs, or NestJS 12 `schema` options with `StandardSchemaValidationPipe` (whose `transform: false` returns the original input, unknown keys included).
- [ ] 🔴 No `@Body() body: any` (or an untyped object) reaching persistence: a DTO or a schema per operation.
- [ ] 🟡 Nested DTOs pair `@ValidateNested()` with `@Type(() => Dto)` (arrays add `{ each: true }` and `@IsArray()`); without `@Type`, the strict global pipe rejects every nested object and `whitelist` alone empties it.
- [ ] 🟢 `@IsOptional()` on a nested object only matters when `null` must be accepted or other validators apply: an omitted value already passes `@ValidateNested()`.
- [ ] 💡 PATCH uses `PartialType(CreateDto)`; PUT may reuse the create DTO.

### Guards & interceptors → [Guard / Interceptor / Pipe](#guard--interceptor--pipe)

- [ ] 🔴 A guard or service that loads a resource for an ownership check handles "not found" (no `null.userId` TypeError and 500) and compares against the authenticated user, never a client-supplied owner ID.
- [ ] 🟡 Guards read metadata with `Reflector.getAllAndOverride()` over handler and class, and deny rather than crash when `request.user` is missing. Store lookups in guards (API keys, sessions, policies) are fine.
- [ ] 🟡 Interceptors hold cross-cutting concerns (logging, caching, response mapping, timing), not business rules, and log through the application's logger.

### Errors → [Error Handling](#error-handling)

- [ ] 🟡 No `catch { return null }` that makes "failed" look like "not found"; services throw meaningful exceptions.
- [ ] 🟡 A catch-all `@Catch()` filter keeps `HttpException` bodies (validation messages), replies through the platform adapter (`BaseExceptionFilter` or `HttpAdapterHost`), hides unknown errors behind a generic 500, and branches on `host.getType()` when the app also serves GraphQL, microservices, or WebSockets.
- [ ] 🟢 Built-in exceptions (`NotFoundException`, `ConflictException`, …) rather than `new HttpException(message, code)`.

### DI & modules → [Dependency Injection & Layered Architecture](#dependency-injection--layered-architecture)

- [ ] 🟡 A `Scope.REQUEST` provider is justified: it makes every consumer request-scoped, and lifecycle hooks do not run on those instances; per-request context comes from `AsyncLocalStorage` (for example `nestjs-cls`).
- [ ] 🟡 No new circular module imports; a `forwardRef()` carries a design note.
- [ ] 💡 Interface-plus-token injection only where a port has several implementations; concrete class providers are already swappable in tests.

### Lifecycle → [Lifecycle & Runtime](#lifecycle--runtime)

- [ ] 🟡 When the PR touches `main.ts` or providers that own connections: `app.enableShutdownHooks()` is called, and pools, clients, and consumers close in `onModuleDestroy`/`onApplicationShutdown`.
- [ ] 🟡 NestJS 12 upgrades re-check hook-order assumptions, ESM-only packages (Jest needs Node.js 24.9+), and the Node.js floor (20.19+ or 22.12+).

### Testing → [Testing Patterns](#testing-patterns)

- [ ] 🟡 E2E tests get the production pipes, guards, and filters from the module (`APP_PIPE`, `APP_GUARD`, `APP_FILTER`) or from one shared setup function, and close the app in `afterAll`.
- [ ] 💡 Use cases are unit-tested by constructing them with fakes, or with `overrideProvider()`.

### House conventions → [Module Organization](#module-organization)

Apply these only when the repository already follows them; otherwise they are 💡 suggestions at most.

- [ ] 🟢 Controllers delegate to services; no ORM client in a controller; repositories do not inject each other.
- [ ] 💡 A service with more dependencies than the repository's own threshold splits into use-case services.
- [ ] 🟢 Folder placement (`common/`, `core/`, `integrations/`, `modules/<feature>/`) and framework-free domain classes; ORM entities and schemas are decorated by design and are never findings.

---

## Validation Patterns (DTO)

Register the global pipe as a provider, so e2e tests built from `AppModule` get the same validation as production:

```typescript
import { Module, ValidationPipe } from '@nestjs/common';
import { APP_PIPE } from '@nestjs/core';

// ✅ class-validator DTOs: strip or reject unknown properties, transform payloads into DTO instances
@Module({
  providers: [
    { provide: APP_PIPE, useValue: new ValidationPipe({ whitelist: true, forbidNonWhitelisted: true, transform: true }) },
  ],
})
export class AppModule {}
```

NestJS 12 also accepts a Standard Schema (Zod, Valibot, ArkType) per parameter: `@Body({ schema: createUserSchema }) body: CreateUser` with `StandardSchemaValidationPipe` registered globally. With its default `transform: true` the handler receives the schema's output (a Zod `z.object` strips unknown keys); `transform: false` hands back the original input.

```typescript
export class CreateOrderDto {
  // ❌ @ValidateNested() alone leaves the nested value a plain object. With whitelist + forbidNonWhitelisted
  //    every request fails ("shipping.property street should not exist"); with whitelist alone shipping
  //    is emptied to {}; without whitelist nothing inside it is validated
  // ✅ Pair it with @Type
  @ValidateNested()
  @Type(() => AddressDto)
  shipping: AddressDto;

  @IsArray()
  @ValidateNested({ each: true })
  @Type(() => OrderItemDto)
  items: OrderItemDto[];

  @IsOptional() // needed only to accept null: an omitted billing already skips @ValidateNested
  @ValidateNested()
  @Type(() => AddressDto)
  billing?: AddressDto | null;
}
```

A handler that takes `@Body() body: any` gets no validation, no types, and no API documentation. PATCH endpoints take `UpdateDto extends PartialType(CreateDto)` (from `@nestjs/mapped-types` or `@nestjs/swagger`) so every field is optional; a PUT that replaces the whole resource can reuse the create DTO.

---

## Guard / Interceptor / Pipe

```typescript
// ❌ A missing order throws TypeError (a 500), and the ownership rule is hidden in a guard
async canActivate(context: ExecutionContext): Promise<boolean> {
  const req = context.switchToHttp().getRequest();
  const order = await this.prisma.order.findUnique({ where: { id: req.params.id } });
  return order.userId === req.user.id;
}

// ✅ A role guard: metadata from the handler, then the class; a request without a user is denied, not a crash
@Injectable()
export class RolesGuard implements CanActivate {
  constructor(private readonly reflector: Reflector) {}

  canActivate(context: ExecutionContext): boolean {
    const requiredRoles = this.reflector.getAllAndOverride<string[] | undefined>('roles', [
      context.getHandler(),
      context.getClass(),
    ]);
    if (!requiredRoles) return true;
    const { user } = context.switchToHttp().getRequest<{ user?: { roles?: string[] } }>();
    return requiredRoles.some((role) => user?.roles?.includes(role) ?? false);
  }
}
```

Ownership checks can live in a guard or in the service. Either way the lookup turns a missing resource into a 404 (or a 403 that does not reveal existence) and compares with the authenticated user. Interceptors that compute discounts or other business results belong in services; timing and logging interceptors use `finalize()` so failures are measured too.

---

## Error Handling

`try { return await this.repo.findById(id); } catch { return null; }` makes an outage look like a miss: let failures propagate, and turn a real miss into ``throw new NotFoundException(`User ${id} not found`)``.

A hand-written catch-all filter that replies with only `statusCode`, `timestamp`, and `path` discards every `HttpException` body, including the ValidationPipe's messages, and `response.status().json()` ties it to Express.

```typescript
import { ArgumentsHost, Catch } from '@nestjs/common';
import { BaseExceptionFilter } from '@nestjs/core';

// ✅ HttpException bodies pass through, unknown errors become a logged generic 500, and replies go through
//    the platform adapter (Express or Fastify). HTTP only: apps that also serve GraphQL, microservices, or
//    WebSockets branch on host.getType() and use those contexts' own exception handling
@Catch()
export class AllExceptionsFilter extends BaseExceptionFilter {
  override catch(exception: unknown, host: ArgumentsHost): void {
    // report to error tracking here, then delegate
    super.catch(exception, host);
  }
}
// Register with { provide: APP_FILTER, useClass: AllExceptionsFilter } so Nest injects the HTTP adapter
```

Cross-language principles (fail fast, add context, handle each error once): [Error Handling Principles](cross-cutting/error-handling-principles.md).

---

## Dependency Injection & Layered Architecture

Nest can override any provider in tests, concrete classes included, so a token is not needed for testability:

```typescript
const moduleRef = await Test.createTestingModule({ providers: [UsersService, TypeOrmUserRepository] })
  .overrideProvider(TypeOrmUserRepository)
  .useValue(new InMemoryUserRepository())
  .compile();
```

An interface plus a `Symbol` token (`{ provide: USER_REPOSITORY, useClass: TypeOrmUserRepository }` and `@Inject(USER_REPOSITORY) private readonly repo: UserRepository`) earns its place when several implementations exist, per tenant, per region, or in memory for local runs.

A `Scope.REQUEST` provider makes every provider and controller that injects it request-scoped too, so Nest rebuilds that part of the graph for every request, and lifecycle hooks never run on those instances. Keep providers singletons and carry per-request context in `AsyncLocalStorage`, for example with `nestjs-cls`, which the NestJS docs present as an alternative to request-scoped providers ([ALS in Node.js](nodejs.md#async-error-handling)).

```typescript
import { randomUUID } from 'node:crypto';
import type { Request } from 'express';
import { ClsModule } from 'nestjs-cls';

// ✅ Singletons; nestjs-cls keeps per-request values in AsyncLocalStorage
@Module({
  imports: [
    ClsModule.forRoot({
      global: true,
      middleware: {
        mount: true,
        setup: (cls, req: Request) => {
          const incoming = req.headers['x-request-id'];
          cls.set('requestId', typeof incoming === 'string' ? incoming : randomUUID());
        },
      },
    }),
  ],
})
export class AppModule {}
// Singleton services inject ClsService and read this.cls.get('requestId')
```

Circular module imports (`OrdersModule` ↔ `UsersModule`) resolve by moving the shared provider into a third module both import, by publishing events instead of calling back, or by lifting the orchestration into a higher-level service; `forwardRef()` is the last resort and needs a design note.

---

## Module Organization

These are house conventions: apply them only when the repository already follows them.

- Layering: controllers delegate to services, services own business rules and orchestration, and repositories wrap data access without injecting each other.
- A service whose dependency list keeps growing splits into use-case services (one operation per class), measured against the repository's own threshold rather than a fixed number.
- Folders: `common/` holds guards, filters, interceptors, and decorators with no business logic; `core/` holds configuration, database, and queue setup; `integrations/` wraps one external service per directory; `modules/<feature>/` holds DTOs, repositories, services, the controller, and the module.
- Domain classes stay framework-free where the repository separates domain from persistence; ORM entities (TypeORM, MikroORM) and Mongoose schemas are decorated by design.

---

## Testing Patterns

```typescript
describe('UsersController (e2e)', () => {
  let app: INestApplication;

  beforeAll(async () => {
    // AppModule provides the ValidationPipe, guards, and filters (APP_PIPE, APP_GUARD, APP_FILTER),
    // so the test runs the production configuration without copying it
    const moduleRef = await Test.createTestingModule({ imports: [AppModule] }).compile();
    app = moduleRef.createNestApplication();
    await app.init();
  });

  afterAll(async () => {
    await app.close(); // releases servers and pools; open handles keep the runner alive
  });

  it('rejects unknown fields', async () => {
    await request(app.getHttpServer())
      .post('/users')
      .send({ email: 'ann@example.com', name: 'Ann', role: 'admin' })
      .expect(400);
  });
});
```

Configuration applied only in `main.ts` (`app.useGlobalPipes(...)`) is missing from such tests unless both call one shared setup function. Use-case classes can be unit-tested without Nest: `new CreateUserHandler(new InMemoryUserRepository())`.

---

## Lifecycle & Runtime

### Enable shutdown hooks

Nest runs `onModuleDestroy`, `beforeApplicationShutdown`, and `onApplicationShutdown` when `app.close()` is called, but reacts to `SIGTERM` only after `app.enableShutdownHooks()`; without it, a rolling deploy stops the process with pools and consumers still open. NestJS 12 calls lifecycle hooks by component hierarchy level, which can change their order, so re-check teardown that relies on one provider closing before another.

In `main.ts`, call `app.enableShutdownHooks()` before `app.listen()`, and let each provider close what it owns (`async onModuleDestroy() { await this.queue.close(); }`). Signal handling, connection draining, and forced-exit timers: [nodejs.md](nodejs.md#process-lifecycle--graceful-shutdown).

### NestJS 12 changes

Core packages ship as ESM only (CommonJS applications load them through `require(esm)`); Jest can load them only on Node.js 24.9 or later (older versions fail with `ERR_REQUIRE_ASYNC_MODULE`), and new ESM projects default to Vitest. Applications need Node.js 20.19+ or 22.12+. Generated projects lint with Oxlint, the CLI moves to TypeScript 6, and `nest build` with its Swagger and GraphQL plugins uses the TypeScript API, so builds stay on TypeScript 6 while TypeScript 7 checks types ([typescript.md](typescript.md#check-tooling-before-upgrading-to-typescript-7)). TypeScript settings Nest needs (`experimentalDecorators`, `emitDecoratorMetadata`, `strictPropertyInitialization: false`, no `erasableSyntaxOnly`) are covered in [typescript.md](typescript.md#modern-typescript-features).

---

## References

- [NestJS documentation](https://docs.nestjs.com/)
- [NestJS migration guide](https://docs.nestjs.com/migration-guide)
