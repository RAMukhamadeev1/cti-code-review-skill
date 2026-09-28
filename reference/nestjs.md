# NestJS Code Review Guide

Review guidance for NestJS applications: dependency injection and layered architecture, module organization, Guard/Interceptor/Pipe responsibilities, DTO validation, error handling, circular dependencies, testing patterns, and lifecycle and runtime concerns.

> **Related guides:** NestJS code is TypeScript on Node.js. Load [typescript.md](typescript.md) for type-level issues and [javascript.md](javascript.md) for async and Promise pitfalls. Load [nodejs.md](nodejs.md) when the change touches bootstrap (`main.ts`), shutdown, streams, configuration, or other process-level concerns.

## Table of Contents

- [Dependency Injection & Layered Architecture](#dependency-injection--layered-architecture)
- [Module Organization](#module-organization)
- [Guard / Interceptor / Pipe](#guard--interceptor--pipe)
- [Validation Patterns (DTO)](#validation-patterns-dto)
- [Error Handling](#error-handling)
- [Circular Dependencies](#circular-dependencies)
- [Testing Patterns](#testing-patterns)
- [Lifecycle & Runtime](#lifecycle--runtime)
- [Review Checklist](#review-checklist)

---

## Dependency Injection & Layered Architecture

### Three-layer architecture: Controller → Service → Repository

```typescript
// ❌ ORM injected straight into the Controller, skipping the Service layer
@Controller('users')
export class UsersController {
  constructor(private readonly prisma: PrismaService) {}

  @Get()
  findAll() {
    return this.prisma.user.findMany();
  }
}

// ✅ Controller → Service → Repository
@Controller('users')
export class UsersController {
  constructor(private readonly usersService: UsersService) {}

  @Get()
  findAll() {
    return this.usersService.findAll();
  }
}

@Injectable()
export class UsersService {
  constructor(private readonly usersRepo: UsersRepository) {}

  findAll() {
    return this.usersRepo.findAll();
  }
}
```

### Repositories should not inject each other

```typescript
// ❌ A Repository injects another Repository; orchestration belongs in a Service
@Injectable()
export class OrdersRepository {
  constructor(private readonly usersRepository: UsersRepository) {}
}

// ✅ Cross-repository orchestration happens in the Service
@Injectable()
export class OrdersService {
  constructor(
    private readonly ordersRepo: OrdersRepository,
    private readonly usersRepo: UsersRepository,
  ) {}
}
```

### God service: split it once it has more than 8 dependencies

```typescript
// ❌ A giant Service with 9 dependencies
@Injectable()
export class OrdersService {
  constructor(
    private readonly ordersRepo: OrdersRepository,
    private readonly usersRepo: UsersRepository,
    private readonly productsRepo: ProductsRepository,
    private readonly paymentsService: PaymentsService,
    private readonly mailerService: MailerService,
    private readonly inventoryService: InventoryService,
    private readonly discountService: DiscountService,
    private readonly taxService: TaxService,
    private readonly auditService: AuditService,
  ) {}
}

// ✅ Split into use-case services (one operation per file)
@Injectable()
export class CreateOrderService {
  constructor(
    private readonly ordersRepo: OrdersRepository,
    private readonly paymentsService: PaymentsService,
  ) {}

  async execute(dto: CreateOrderDto) { /* ... */ }
}
```

### Dependency inversion with Symbol tokens

```typescript
// ❌ Depends directly on a concrete implementation; it cannot be swapped in tests
@Injectable()
export class UsersService {
  constructor(private readonly repo: TypeOrmUserRepository) {}
}

// ✅ Interface + Symbol token; it can be swapped for an in-memory implementation
export const USER_REPOSITORY = Symbol('USER_REPOSITORY');

export interface UserRepository {
  findAll(): Promise<User[]>;
  findById(id: string): Promise<User | null>;
}

// module:
{
  provide: USER_REPOSITORY,
  useClass: TypeOrmUserRepository,
}

// service:
@Injectable()
export class UsersService {
  constructor(@Inject(USER_REPOSITORY) private readonly repo: UserRepository) {}
}
```

---

## Module Organization

### Recommended four-layer structure

```text
src/
  common/         ← Global technical infrastructure (Guards, Filters, Interceptors, Decorators)
  core/           ← Internal infrastructure (Config, Database, Queue setup)
  integrations/   ← Wrappers for external services (Mailer, Storage, Stripe, SMS)
  modules/        ← Business logic organized by domain
    [feature]/
      dtos/
      repositories/
      services/
        internal/     ← Services shared inside the module
        use-cases/    ← One file = one operation
      types/
      [feature].controller.ts
      [feature].module.ts
```

### The domain must be framework-agnostic

```typescript
// ❌ The domain entity depends on NestJS and cannot be tested on its own
import { Injectable } from '@nestjs/common';

@Injectable()
export class User {
  constructor(private readonly email: string) {}
}

// ✅ Domain entities are plain classes without framework decorators
export class User {
  private constructor(private readonly email: string) {}

  static create(email: string): User {
    return new User(email);
  }
}
```

### Key rules

- `common/` must contain **no business logic**: if it needs to know about "orders", it does not belong there
- `integrations/` wraps each external service; switching from SendGrid to AWS SES changes a single directory
- Use **use-case services** (one operation per file) instead of a giant `XxxService` with 15 methods

---

## Guard / Interceptor / Pipe

### Business logic does not belong in guards

```typescript
// ❌ The Guard queries the database and makes a business decision
@Injectable()
export class OrderOwnershipGuard implements CanActivate {
  constructor(private readonly prisma: PrismaService) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const req = context.switchToHttp().getRequest();
    const order = await this.prisma.order.findUnique({
      where: { id: req.params.id },
    });
    if (order.userId !== req.user.id) {
      return false; // Data access and the business rule both live in the Guard
    }
    return true;
  }
}

// ✅ The Guard only checks authorization (roles/permissions)
@Injectable()
export class RolesGuard implements CanActivate {
  constructor(private readonly reflector: Reflector) {}

  canActivate(context: ExecutionContext): boolean {
    const requiredRoles = this.reflector.getAllAndOverride<string[]>('roles', [
      context.getHandler(),
      context.getClass(),
    ]);
    if (!requiredRoles) return true;
    const { user } = context.switchToHttp().getRequest();
    return requiredRoles.some((role) => user.roles?.includes(role));
  }
}
```

### Use interceptors only for cross-cutting concerns

```typescript
// ❌ Business logic inside an Interceptor
@Injectable()
export class PricingInterceptor implements NestInterceptor {
  intercept(context: ExecutionContext, next: CallHandler) {
    // Calculating discounts is not a cross-cutting concern!
    return next.handle().pipe(map(data => applyDiscount(data)));
  }
}

// ✅ Interceptors for logging, caching, response mapping, and timing
@Injectable()
export class LoggingInterceptor implements NestInterceptor {
  intercept(context: ExecutionContext, next: CallHandler) {
    const now = Date.now();
    const req = context.switchToHttp().getRequest();
    return next.handle().pipe(
      tap(() => console.log(`${req.method} ${req.url} - ${Date.now() - now}ms`)),
    );
  }
}
```

### The global ValidationPipe must set whitelist

```typescript
// ❌ No whitelist: extra properties in the request body pass straight through
async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  await app.listen(3000);
}

// ✅ A global ValidationPipe with whitelist strips unknown properties
async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  app.useGlobalPipes(
    new ValidationPipe({
      whitelist: true,
      forbidNonWhitelisted: true,
      transform: true,
    }),
  );
  await app.listen(3000);
}
```

---

## Validation Patterns (DTO)

### `@ValidateNested()` must be paired with `@Type()`

```typescript
// ❌ @ValidateNested alone: validation of the nested object is silently skipped!
export class CreateOrderDto {
  @ValidateNested()
  shipping: AddressDto;
}

// ✅ Use @ValidateNested and @Type together
import { Type } from 'class-transformer';

export class CreateOrderDto {
  @ValidateNested()
  @Type(() => AddressDto)
  shipping: AddressDto;

  @IsArray()
  @ValidateNested({ each: true })
  @Type(() => OrderItemDto)
  items: OrderItemDto[];
}
```

### No bare `any` body

```typescript
// ❌ No DTO: no validation, no type safety, no Swagger docs
@Post()
create(@Body() body: any) {
  return this.service.create(body);
}

// ✅ Create a DTO for every operation
export class CreateUserDto {
  @IsEmail()
  email: string;

  @IsString()
  @MinLength(2)
  @MaxLength(100)
  name: string;
}

@Post()
create(@Body() dto: CreateUserDto) {
  return this.service.create(dto);
}
```

### Create and update should use different DTOs

```typescript
// ❌ PATCH also requires every field, which is poor API design
@Patch(':id')
update(@Body() dto: CreateUserDto) { /* all fields required */ }

// ✅ Update uses PartialType
export class UpdateUserDto extends PartialType(CreateUserDto) {}

@Patch(':id')
update(@Body() dto: UpdateUserDto) { /* all fields optional */ }
```

### Optional nested objects

```typescript
// ❌ Optional nested object without @IsOptional
export class UpdateOrderDto {
  @ValidateNested()
  @Type(() => AddressDto)
  shipping?: AddressDto; // Validation still runs when it is undefined
}

// ✅ @IsOptional + @ValidateNested + @Type
export class UpdateOrderDto {
  @IsOptional()
  @ValidateNested()
  @Type(() => AddressDto)
  shipping?: AddressDto;
}
```

---

## Error Handling

### Never swallow errors

```typescript
// ❌ catch { return null } hides the problem: callers cannot tell "not found" from "failed"
async findOne(id: string) {
  try {
    return await this.repo.findById(id);
  } catch (e) {
    return null;
  }
}

// ✅ Throw a meaningful exception
async findOne(id: string): Promise<User> {
  const user = await this.repo.findById(id);
  if (!user) {
    throw new NotFoundException(`User ${id} not found`);
  }
  return user;
}
```

> 📖 Cross-language principles (don't swallow errors, add context, use specific types, fail fast, handle each error once): [Error Handling Principles](cross-cutting/error-handling-principles.md#core-principles).

### Use the built-in exception classes

```typescript
// ❌ Building the HTTP error by hand
throw new HttpException('Bad request', 400);

// ✅ Use the semantic built-in exceptions
throw new BadRequestException('Invalid email format');
throw new NotFoundException('User not found');
throw new ConflictException('Email already taken');
throw new ForbiddenException('Insufficient permissions');
throw new UnauthorizedException('Invalid credentials');
```

### Custom exception filters

```typescript
// ✅ A global exception filter gives every error the same response format
@Catch()
export class AllExceptionsFilter implements ExceptionFilter {
  private readonly logger = new Logger(AllExceptionsFilter.name);

  catch(exception: unknown, host: ArgumentsHost) {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse();
    const request = ctx.getRequest();

    const status =
      exception instanceof HttpException
        ? exception.getStatus()
        : HttpStatus.INTERNAL_SERVER_ERROR;

    this.logger.error(`${request.method} ${request.url} - ${status}`, exception instanceof Error ? exception.stack : '');

    response.status(status).json({
      statusCode: status,
      timestamp: new Date().toISOString(),
      path: request.url,
    });
  }
}
```

---

## Circular Dependencies

### Circular references between modules

```typescript
// ❌ Module A ↔ Module B
@Module({ imports: [UsersModule] })
export class OrdersModule {}

@Module({ imports: [OrdersModule] })
export class UsersModule {}

// ✅ Move the shared logic into a third module
@Module({
  providers: [SharedService],
  exports: [SharedService],
})
export class SharedModule {}

@Module({ imports: [SharedModule] })
export class OrdersModule {}

@Module({ imports: [SharedModule] })
export class UsersModule {}
```

### `forwardRef` is a last resort

```typescript
// ⚠️ forwardRef signals a design problem; redesign first
@Module({
  imports: [forwardRef(() => UsersModule)],
})
export class OrdersModule {}

// ✅ Redesign to remove the cycle:
// 1. Extract a shared module
// 2. Use events (EventEmitter) instead of direct calls
// 3. Move the shared logic up into a higher-level Service
```

---

## Testing Patterns

### Use cases can be tested without NestJS

```typescript
// ✅ No NestFactory needed: construct the handler directly
describe('CreateUserHandler', () => {
  let handler: CreateUserHandler;
  let repo: InMemoryUserRepository;

  beforeEach(() => {
    repo = new InMemoryUserRepository();
    handler = new CreateUserHandler(repo);
  });

  it('creates a user', async () => {
    const id = await handler.execute(
      new CreateUserCommand('user@example.com', 'Alice'),
    );
    expect(id).toBeDefined();
  });

  it('rejects duplicate email', async () => {
    await handler.execute(new CreateUserCommand('user@example.com', 'Alice'));
    await expect(
      handler.execute(new CreateUserCommand('user@example.com', 'Bob')),
    ).rejects.toThrow('already exists');
  });
});
```

### E2E tests should configure the same pipes as production

```typescript
describe('UsersController (e2e)', () => {
  let app: INestApplication;

  beforeAll(async () => {
    const moduleFixture = await Test.createTestingModule({
      imports: [AppModule],
    }).compile();

    app = moduleFixture.createNestApplication();
    // Must match the global configuration in main.ts
    app.useGlobalPipes(
      new ValidationPipe({
        whitelist: true,
        forbidNonWhitelisted: true,
        transform: true,
      }),
    );
    await app.init();
  });

  it('/POST users - valid', () => {
    return request(app.getHttpServer())
      .post('/users')
      .send({ email: 'test@test.com', name: 'Test' })
      .expect(201);
  });

  it('/POST users - extra fields rejected', () => {
    return request(app.getHttpServer())
      .post('/users')
      .send({ email: 'test@test.com', name: 'Test', role: 'admin' })
      .expect(400);
  });
});
```

---

## Lifecycle & Runtime

### Enable shutdown hooks

Nest runs `onModuleDestroy`, `beforeApplicationShutdown`, and `onApplicationShutdown` when `app.close()` is called, but it reacts to SIGTERM only after `app.enableShutdownHooks()`. Without that call, a rolling deploy stops the process with database pools and queue consumers still open. NestJS 12 calls these hooks by component hierarchy level, which can change their order, so re-check teardown code that relies on one provider closing before another.

```typescript
// ✅ main.ts: without enableShutdownHooks(), SIGTERM ends the process and no destroy hook runs
async function bootstrap() {
  const app = await NestFactory.create(AppModule);
  app.enableShutdownHooks();
  await app.listen(3000);
}

// ✅ Each provider closes the connections and consumers it owns
@Injectable()
export class OrdersConsumer implements OnModuleDestroy {
  constructor(private readonly queue: QueueClient) {}

  async onModuleDestroy() {
    await this.queue.close();
  }
}
```

> 📖 Signal handling, connection draining, and forced-exit timers: [nodejs.md](nodejs.md#process-lifecycle--graceful-shutdown).

### Request-scoped providers bubble up the injection chain

A `Scope.REQUEST` provider makes every provider and controller that injects it request-scoped as well, so Nest rebuilds that part of the graph for every request, and lifecycle hooks never run on those instances. Keep providers singletons and carry per-request context in `AsyncLocalStorage`, for example with `nestjs-cls`, which the NestJS docs present as an alternative to request-scoped providers.

```typescript
// ❌ OrdersService, and every controller that injects it, become request-scoped
@Injectable({ scope: Scope.REQUEST })
export class RequestContext {
  constructor(@Inject(REQUEST) readonly request: Request) {}
}

@Injectable()
export class OrdersService {
  constructor(private readonly context: RequestContext) {}
}

// ✅ Singletons; nestjs-cls keeps per-request values in AsyncLocalStorage
@Module({
  imports: [
    ClsModule.forRoot({
      global: true,
      middleware: {
        mount: true,
        setup: (cls, req) => cls.set('requestId', req.headers['x-request-id'] ?? randomUUID()),
      },
    }),
  ],
})
export class AppModule {}

// Singleton services inject ClsService and read the value: this.cls.get('requestId')
```

---

## Review Checklist

### Layered architecture
- [ ] ORM/Prisma clients are not injected directly into Controllers
- [ ] No business logic in Controllers
- [ ] Repositories do not inject each other
- [ ] Services have ≤ 8 dependencies (split into use cases beyond that)

### Dependency injection
- [ ] Interfaces + Symbol tokens are used for swappable dependencies
- [ ] No `forwardRef()` (if there is one, a design note explains why)
- [ ] Scoped services are not injected into singletons (request scope bubbles up to every consumer)

### Validation
- [ ] Every `@ValidateNested()` has a matching `@Type()`
- [ ] A global `ValidationPipe({ whitelist: true, forbidNonWhitelisted: true })` is configured
- [ ] No `@Body() body: any`; a DTO is required
- [ ] Create and Update use different DTOs (`PartialType`)
- [ ] Array validation uses `{ each: true }`
- [ ] Optional nested objects use `@IsOptional()` + `@ValidateNested()` + `@Type()`

### Guard / Interceptor / Pipe
- [ ] Guards only check authorization and do not query the database
- [ ] Interceptors only handle cross-cutting concerns (logging, caching, response mapping)
- [ ] Business rules live in Services

### Error handling
- [ ] No `catch { return null }`; meaningful exceptions are thrown
- [ ] NestJS built-in exception classes are used
- [ ] Custom exception filters live in `common/filters/`

### Modules
- [ ] No circular module imports
- [ ] Domain entities have no framework decorators (`@Injectable`, etc.)
- [ ] External service calls live in `integrations/`

### Testing
- [ ] Use-case services can be tested without NestJS
- [ ] E2E tests configure the same global Pipes/Guards as production
- [ ] Domain entities have zero framework dependencies

### Lifecycle
- [ ] `main.ts` calls `app.enableShutdownHooks()`
- [ ] Providers that own connections, pools, or consumers release them in `onModuleDestroy` or `onApplicationShutdown`
- [ ] Any `Scope.REQUEST` provider is justified; per-request context otherwise comes from `AsyncLocalStorage` (for example `nestjs-cls`)
