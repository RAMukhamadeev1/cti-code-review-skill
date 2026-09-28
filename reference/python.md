# Python Code Review Guide

> Python code review guide covering core topics such as type annotations, async/await, testing, exception handling, and performance optimization.
>
> **Related guides:** for Python services also apply the [Security Review Guide](security-review-guide.md), [N+1 Queries](cross-cutting/n-plus-one-queries.md), [Async & Concurrency Patterns](cross-cutting/async-concurrency-patterns.md), and [Error Handling Principles](cross-cutting/error-handling-principles.md).

## Table of Contents

- [Type Annotations](#type-annotations)
- [Asynchronous Programming](#asynchronous-programming)
- [Exception Handling](#exception-handling)
- [Common Pitfalls](#common-pitfalls)
- [Testing Best Practices](#testing-best-practices)
- [Performance Optimization](#performance-optimization)
- [Code Style](#code-style)
- [Review Checklist](#review-checklist)

---

## Type Annotations

### Basic type annotations

```python
# ❌ No type annotations, so the IDE can't help
def process_data(data, count):
    return data[:count]

# ✅ Use type annotations
def process_data(data: str, count: int) -> str:
    return data[:count]

# ✅ Use the typing module for complex types
from typing import Optional, Union

def find_user(user_id: int) -> Optional[User]:
    """Return the user or None."""
    return db.get(user_id)

def handle_input(value: Union[str, int]) -> str:
    """Accept a string or an integer."""
    return str(value)
```

### Container type annotations

```python
from typing import List, Dict, Set, Tuple, Sequence

# ❌ Imprecise types
def get_names(users: list) -> list:
    return [u.name for u in users]

# ✅ Precise container types (on Python 3.9+, write list[User] directly)
def get_names(users: List[User]) -> List[str]:
    return [u.name for u in users]

# ✅ Use Sequence for read-only sequences (more flexible)
def process_items(items: Sequence[str]) -> int:
    return len(items)

# ✅ Dictionary types
def count_words(text: str) -> Dict[str, int]:
    words: Dict[str, int] = {}
    for word in text.split():
        words[word] = words.get(word, 0) + 1
    return words

# ✅ Tuples (fixed length and element types)
def get_point() -> Tuple[float, float]:
    return (1.0, 2.0)

# ✅ Variable-length tuples
def get_scores() -> Tuple[int, ...]:
    return (90, 85, 92, 88)
```

### Generics and TypeVar

```python
from typing import TypeVar, Generic, Dict, List, Callable

T = TypeVar('T')
K = TypeVar('K')
V = TypeVar('V')

# ✅ Generic function
def first(items: List[T]) -> T | None:
    return items[0] if items else None

# ✅ Bounded TypeVar
from typing import Hashable
H = TypeVar('H', bound=Hashable)

def dedupe(items: List[H]) -> List[H]:
    return list(set(items))

# ✅ Generic class
class Cache(Generic[K, V]):
    def __init__(self) -> None:
        self._data: Dict[K, V] = {}

    def get(self, key: K) -> V | None:
        return self._data.get(key)

    def set(self, key: K, value: V) -> None:
        self._data[key] = value
```

### Callable and callback functions

```python
from typing import Callable, Awaitable

# ✅ Function type annotations
Handler = Callable[[str, int], bool]

def register_handler(name: str, handler: Handler) -> None:
    handlers[name] = handler

# ✅ Async callbacks
AsyncHandler = Callable[[str], Awaitable[dict]]

async def fetch_with_handler(
    url: str,
    handler: AsyncHandler
) -> dict:
    return await handler(url)

# ✅ Functions that return functions
def create_multiplier(factor: int) -> Callable[[int], int]:
    def multiplier(x: int) -> int:
        return x * factor
    return multiplier
```

### TypedDict and structured data

```python
from typing import TypedDict, Required, NotRequired

# ✅ Define the structure of a dict
class UserDict(TypedDict):
    id: int
    name: str
    email: str
    age: NotRequired[int]  # Python 3.11+

def create_user(data: UserDict) -> User:
    return User(**data)

# ✅ Only some fields required
class ConfigDict(TypedDict, total=False):
    debug: bool
    timeout: int
    host: Required[str]  # This one is required
```

### Protocol and structural subtyping

```python
from typing import Protocol, runtime_checkable

# ✅ Define a protocol (type checking for duck typing)
class Readable(Protocol):
    def read(self, size: int = -1) -> bytes: ...

class Closeable(Protocol):
    def close(self) -> None: ...

# Combine protocols
class ReadableCloseable(Readable, Closeable, Protocol):
    pass

def process_stream(stream: Readable) -> bytes:
    return stream.read()

# ✅ Runtime-checkable protocol
@runtime_checkable
class Drawable(Protocol):
    def draw(self) -> None: ...

def render(obj: object) -> None:
    if isinstance(obj, Drawable):  # Checked at runtime
        obj.draw()
```

---

## Asynchronous Programming

> 📖 For general concurrency patterns and cross-language examples, see the [Async & Concurrency Patterns guide](cross-cutting/async-concurrency-patterns.md).

### async/await basics

```python
import asyncio

# ❌ Synchronous, blocking calls
def fetch_all_sync(urls: list[str]) -> list[str]:
    results = []
    for url in urls:
        results.append(requests.get(url).text)  # Runs sequentially
    return results

# ✅ Asynchronous, concurrent calls
async def fetch_url(session: aiohttp.ClientSession, url: str) -> str:
    async with session.get(url) as response:
        return await response.text()

async def fetch_all(urls: list[str]) -> list[str]:
    # Reuse one session (connection pool) for all requests
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_url(session, url) for url in urls]
        return await asyncio.gather(*tasks)  # Runs concurrently
```

### Async context managers

```python
from contextlib import asynccontextmanager
from typing import AsyncIterator

# ✅ Async context manager class
class AsyncDatabase:
    async def __aenter__(self) -> 'AsyncDatabase':
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()

# ✅ Use a decorator
@asynccontextmanager
async def get_connection() -> AsyncIterator[Connection]:
    conn = await create_connection()
    try:
        yield conn
    finally:
        await conn.close()

async def query_data():
    async with get_connection() as conn:
        return await conn.fetch("SELECT * FROM users")
```

### Async iterators

```python
from typing import AsyncIterator

# ✅ Async generator
async def fetch_pages(url: str) -> AsyncIterator[dict]:
    page = 1
    while True:
        data = await fetch_page(url, page)
        if not data['items']:
            break
        yield data
        page += 1

# ✅ Use async iteration
async def process_all_pages():
    async for page in fetch_pages("https://api.example.com"):
        await process_page(page)
```

### Task management and cancellation

```python
import asyncio

# ❌ Forgetting to handle cancellation
async def bad_worker():
    while True:
        await do_work()  # Can't be cancelled cleanly

# ✅ Handle cancellation correctly
async def good_worker():
    try:
        while True:
            await do_work()
    except asyncio.CancelledError:
        await cleanup()  # Clean up resources
        raise  # Re-raise so the caller knows it was cancelled

# ✅ Enforce a timeout
async def fetch_with_timeout(session: aiohttp.ClientSession, url: str) -> str:
    try:
        async with asyncio.timeout(10):  # Python 3.11+
            return await fetch_url(session, url)
    except asyncio.TimeoutError:
        return ""

# ✅ Task groups (Python 3.11+)
async def fetch_multiple():
    async with aiohttp.ClientSession() as session:
        async with asyncio.TaskGroup() as tg:
            task1 = tg.create_task(fetch_url(session, "url1"))
            task2 = tg.create_task(fetch_url(session, "url2"))
        # Exiting the block waits for all tasks; exceptions propagate
        return task1.result(), task2.result()
```

### Mixing sync and async code

```python
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor

# ✅ Run a sync function from async code
async def run_sync_in_async():
    loop = asyncio.get_running_loop()
    # Run the blocking operation in a thread pool
    result = await loop.run_in_executor(
        None,  # Default thread pool
        blocking_io_function,
        arg1, arg2
    )
    return result

# ✅ Run an async function from sync code
def run_async_in_sync():
    return asyncio.run(async_function())

# ❌ Don't use time.sleep in async code
async def bad_delay():
    time.sleep(1)  # Blocks the entire event loop!

# ✅ Use asyncio.sleep
async def good_delay():
    await asyncio.sleep(1)
```

### Semaphores and throttling

```python
import asyncio

# ✅ Limit concurrency with a semaphore
async def fetch_with_limit(urls: list[str], max_concurrent: int = 10):
    semaphore = asyncio.Semaphore(max_concurrent)

    async def fetch_one(session: aiohttp.ClientSession, url: str) -> str:
        async with semaphore:
            return await fetch_url(session, url)

    async with aiohttp.ClientSession() as session:
        return await asyncio.gather(*[fetch_one(session, url) for url in urls])

# ✅ Use asyncio.Queue for producer-consumer
async def producer_consumer():
    queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=100)

    async def producer():
        for item in items:
            await queue.put(item)
        await queue.put(None)  # Sentinel: no more items

    async def consumer():
        while True:
            item = await queue.get()
            if item is None:
                break
            await process(item)
            queue.task_done()

    await asyncio.gather(producer(), consumer())
```

---

## Exception Handling

> 📖 For general principles and cross-language examples, see the [Error Handling Principles guide](cross-cutting/error-handling-principles.md).

### Best practices for catching exceptions

```python
# ❌ Catching too broadly
try:
    result = risky_operation()
except:  # Catches everything, even KeyboardInterrupt!
    pass

# ❌ Catching Exception but not handling it
try:
    result = risky_operation()
except Exception:
    pass  # Swallows every exception; hard to debug

# ✅ Catch specific exceptions
try:
    result = risky_operation()
except ValueError as e:
    logger.error(f"Invalid value: {e}")
    raise
except IOError as e:
    logger.error(f"IO error: {e}")
    result = default_value

# ✅ Multiple exception types
try:
    result = parse_and_process(data)
except (ValueError, TypeError, KeyError) as e:
    logger.error(f"Data error: {e}")
    raise DataProcessingError(str(e)) from e
```

### Exception chaining

```python
# ❌ Original exception not recorded as the cause
try:
    result = external_api.call()
except APIError as e:
    raise RuntimeError("API failed")  # __cause__ is not set

# ✅ Use from to preserve the exception chain
try:
    result = external_api.call()
except APIError as e:
    raise RuntimeError("API failed") from e

# ✅ Explicitly break the exception chain (rare)
try:
    result = external_api.call()
except APIError:
    raise RuntimeError("API failed") from None
```

### Custom exceptions

```python
# ✅ Define a business exception hierarchy
class AppError(Exception):
    """Base exception for the application."""
    pass

class ValidationError(AppError):
    """Data validation error."""
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")

class NotFoundError(AppError):
    """Resource not found."""
    def __init__(self, resource: str, id: str | int):
        self.resource = resource
        self.id = id
        super().__init__(f"{resource} with id {id} not found")

# Usage
def get_user(user_id: int) -> User:
    user = db.get(user_id)
    if not user:
        raise NotFoundError("User", user_id)
    return user
```

### Exceptions in context managers

```python
from contextlib import contextmanager

# ✅ Handle exceptions correctly in a context manager
@contextmanager
def transaction():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ✅ Use ExceptionGroup (Python 3.11+)
def process_batch(items: list) -> None:
    errors = []
    for item in items:
        try:
            process(item)
        except Exception as e:
            errors.append(e)

    if errors:
        raise ExceptionGroup("Batch processing failed", errors)
```

---

## Common Pitfalls

### Mutable default arguments

```python
# ❌ Mutable default arguments
def add_item(item, items=[]):  # Bug! Shared across calls
    items.append(item)
    return items

# Demonstration
add_item(1)  # [1]
add_item(2)  # [1, 2] instead of [2]!

# ✅ Use None as default
def add_item(item, items=None):
    if items is None:
        items = []
    items.append(item)
    return items

# ✅ Or use a dataclass field
from dataclasses import dataclass, field

@dataclass
class Container:
    items: list = field(default_factory=list)
```

### Mutable class attributes

```python
# ❌ Using mutable class attributes
class User:
    permissions = []  # Shared across all instances!

# Demonstration
u1 = User()
u2 = User()
u1.permissions.append("admin")
print(u2.permissions)  # ["admin"] - shared by accident!

# ✅ Initialize in __init__
class User:
    def __init__(self):
        self.permissions = []

# ✅ Use a dataclass
@dataclass
class User:
    permissions: list = field(default_factory=list)
```

### Closures in loops

```python
# ❌ The closure captures the loop variable
funcs = []
for i in range(3):
    funcs.append(lambda: i)

print([f() for f in funcs])  # [2, 2, 2] instead of [0, 1, 2]!

# ✅ Capture the value with a default argument
funcs = []
for i in range(3):
    funcs.append(lambda i=i: i)

print([f() for f in funcs])  # [0, 1, 2]

# ✅ Use functools.partial
from functools import partial

funcs = [partial(lambda x: x, i) for i in range(3)]
```

### is vs ==

```python
# ❌ Using is to compare values
if x is 1000:  # May not work!
    pass

# Python caches small integers (-5 to 256)
a = 256
b = 256
a is b  # True

a = 257
b = 257
a is b  # False!

# ✅ Use == to compare values
if x == 1000:
    pass

# ✅ Use is only for None and singletons
if x is None:
    pass

if x is True:  # Strict boolean check
    pass
```

### String concatenation performance

```python
# ❌ Concatenating strings in a loop
result = ""
for item in large_list:
    result += str(item)  # O(n²) complexity

# ✅ Use join
result = "".join(str(item) for item in large_list)  # O(n)

# ✅ Use StringIO to build large strings
from io import StringIO

buffer = StringIO()
for item in large_list:
    buffer.write(str(item))
result = buffer.getvalue()
```

---

## Testing Best Practices

### pytest basics

```python
import pytest

# ✅ Clear test names
def test_user_creation_with_valid_email():
    user = User(email="test@example.com")
    assert user.email == "test@example.com"

def test_user_creation_with_invalid_email_raises_error():
    with pytest.raises(ValidationError):
        User(email="invalid")

# ✅ Use parametrized tests
@pytest.mark.parametrize("input,expected", [
    ("hello", "HELLO"),
    ("World", "WORLD"),
    ("", ""),
    ("123", "123"),
])
def test_uppercase(input: str, expected: str):
    assert input.upper() == expected

# ✅ Test exceptions
def test_division_by_zero():
    with pytest.raises(ZeroDivisionError) as exc_info:
        1 / 0
    assert "division by zero" in str(exc_info.value)
```

### Fixtures

```python
import pytest
import pytest_asyncio
from typing import AsyncGenerator, Generator

# ✅ Basic fixture
@pytest.fixture
def user() -> User:
    return User(name="Test User", email="test@example.com")

def test_user_name(user: User):
    assert user.name == "Test User"

# ✅ Fixture with teardown
@pytest.fixture
def database() -> Generator[Database, None, None]:
    db = Database()
    db.connect()
    yield db
    db.disconnect()  # Clean up after the test

# ✅ Async fixture
@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    async with AsyncClient() as client:
        yield client

# ✅ Shared fixtures (conftest.py)
# conftest.py
@pytest.fixture(scope="session")
def app():
    """App instance shared by the entire test session."""
    return create_app()

@pytest.fixture(scope="module")
def db(app):
    """Database connection shared within each test module."""
    return app.db
```

### Mock and patch

```python
import pytest
from unittest.mock import Mock, patch, AsyncMock, ANY

# ✅ Mock external dependencies
def test_send_email():
    mock_client = Mock()
    mock_client.send.return_value = True

    service = EmailService(client=mock_client)
    result = service.send_welcome_email("user@example.com")

    assert result is True
    mock_client.send.assert_called_once_with(
        to="user@example.com",
        subject="Welcome!",
        body=ANY,
    )

# ✅ Patch module-level functions
@patch("myapp.services.external_api.call")
def test_with_patched_api(mock_call):
    mock_call.return_value = {"status": "ok"}

    result = process_data()

    assert result["status"] == "ok"

# ✅ Async mocks
@pytest.mark.asyncio
async def test_async_function():
    mock_fetch = AsyncMock(return_value={"data": "test"})

    with patch("myapp.client.fetch", mock_fetch):
        result = await get_data()

    assert result == {"data": "test"}
```

### Test organization

```python
# ✅ Use a class to group related tests
class TestUserAuthentication:
    """Tests for user authentication."""

    def test_login_with_valid_credentials(self, user):
        assert authenticate(user.email, "password") is True

    def test_login_with_invalid_password(self, user):
        assert authenticate(user.email, "wrong") is False

    def test_login_locks_after_failed_attempts(self, user):
        for _ in range(5):
            authenticate(user.email, "wrong")
        assert user.is_locked is True

# ✅ Tag tests with marks
@pytest.mark.slow
def test_large_data_processing():
    pass

@pytest.mark.integration
def test_database_connection():
    pass

# Select tests by mark: pytest -m "not slow"
```

### Coverage and quality

```python
# pyproject.toml (pytest.ini uses a [pytest] section instead)
[tool.pytest.ini_options]
addopts = "--cov=myapp --cov-report=term-missing --cov-fail-under=80"
testpaths = ["tests"]

# ✅ Test edge cases
def test_empty_input():
    assert process([]) == []

def test_none_input():
    with pytest.raises(TypeError):
        process(None)

def test_large_input():
    large_data = list(range(100000))
    result = process(large_data)
    assert len(result) == 100000
```

---

## Performance Optimization

### Choosing data structures

```python
# ❌ List lookup: O(n)
if item in large_list:  # Slow
    pass

# ✅ Set lookup: O(1)
large_set = set(large_list)
if item in large_set:  # Fast
    pass

# ✅ Use the collections module
from collections import Counter, defaultdict, deque

# Counting
word_counts = Counter(words)
most_common = word_counts.most_common(10)

# Default values for missing keys
graph = defaultdict(list)
graph[node].append(neighbor)

# Double-ended queue (O(1) at both ends)
queue = deque()
queue.appendleft(item)  # O(1) vs list.insert(0, item) O(n)
```

### Generators and iterators

```python
# ❌ Loads all the data at once
def get_all_users():
    return [User(row) for row in db.fetch_all()]  # High memory usage

# ✅ Use a generator
def get_all_users():
    for row in db.fetch_all():
        yield User(row)  # Lazy loading

# ✅ Generator expressions
sum_of_squares = sum(x**2 for x in range(1000000))  # No list is built

# ✅ The itertools module
from itertools import islice, chain, groupby

# Take only the first 10
first_10 = list(islice(infinite_generator(), 10))

# Chain several iterators
all_items = chain(list1, list2, list3)

# Grouping
for key, group in groupby(sorted(items, key=get_key), key=get_key):
    process_group(key, list(group))
```

### Caching

```python
import time
from functools import lru_cache, cache
from typing import Any

# ✅ LRU cache
@lru_cache(maxsize=128)
def expensive_computation(n: int) -> int:
    return sum(i**2 for i in range(n))

# ✅ Unbounded cache (Python 3.9+)
@cache
def fibonacci(n: int) -> int:
    if n < 2:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)

# ✅ Manual caching (when you need more control)
class DataService:
    def __init__(self):
        self._cache: dict[str, Any] = {}
        self._cache_ttl: dict[str, float] = {}

    def get_data(self, key: str) -> Any:
        if key in self._cache:
            if time.time() < self._cache_ttl[key]:
                return self._cache[key]

        data = self._fetch_data(key)
        self._cache[key] = data
        self._cache_ttl[key] = time.time() + 300  # 5 minutes
        return data
```

### Parallel processing

```python
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

# ✅ Thread pool for I/O-bound work
def fetch_all_urls(urls: list[str]) -> list[str]:
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(fetch_url, urls))
    return results

# ✅ Process pool for CPU-bound work
def process_large_dataset(data: list) -> list:
    with ProcessPoolExecutor() as executor:
        results = list(executor.map(heavy_computation, data))
    return results

# ✅ Use as_completed to get results in completion order
from concurrent.futures import as_completed

with ThreadPoolExecutor() as executor:
    futures = {executor.submit(fetch, url): url for url in urls}
    for future in as_completed(futures):
        url = futures[future]
        try:
            result = future.result()
        except Exception as e:
            print(f"{url} failed: {e}")
```

---

## Code Style

### PEP 8 essentials

```python
# ✅ Naming conventions
class MyClass:  # Class names: PascalCase
    MAX_SIZE = 100  # Constants: UPPER_SNAKE_CASE

    def method_name(self):  # Methods: snake_case
        local_var = 1  # Variables: snake_case

# ✅ Import order
# 1. Standard library
import os
import sys
from typing import Optional

# 2. Third-party libraries
import numpy as np
import pandas as pd

# 3. Local modules
from myapp import config
from myapp.utils import helper

# ✅ Line length limit (79 or 88 characters)
# Wrap long expressions
result = (
    long_function_name(arg1, arg2, arg3)
    + another_long_function(arg4, arg5)
)

# ✅ Blank line conventions
class MyClass:
    """Class docstring."""

    def method_one(self):
        pass

    def method_two(self):  # One blank line between methods
        pass


def top_level_function():  # Two blank lines between top-level definitions
    pass
```

### Docstrings

```python
# ✅ Google-style docstring
def calculate_area(width: float, height: float) -> float:
    """Calculate the area of a rectangle.

    Args:
        width: Width of the rectangle (must be positive).
        height: Height of the rectangle (must be positive).

    Returns:
        The area of the rectangle.

    Raises:
        ValueError: If width or height is negative.

    Example:
        >>> calculate_area(3.0, 4.0)
        12.0
    """
    if width < 0 or height < 0:
        raise ValueError("Dimensions must be positive")
    return width * height

# ✅ Class docstring
class DataProcessor:
    """Utility class for processing and transforming data.

    Attributes:
        source: Path of the data source.
        format: Output format ('json' or 'csv').

    Example:
        >>> processor = DataProcessor("data.csv")
        >>> processor.process()
    """
```

### Modern Python features

```python
# ✅ f-strings (Python 3.6+)
name = "World"
print(f"Hello, {name}!")

# ✅ Self-documenting expressions (Python 3.8+)
print(f"Result: {1 + 2 = }")  # "Result: 1 + 2 = 3"

# ✅ Walrus operator (Python 3.8+)
if (n := len(items)) > 10:
    print(f"List has {n} items")

# ✅ Positional-only parameter separator (Python 3.8+)
def greet(name, /, greeting="Hello", *, punctuation="!"):
    """name is positional-only; punctuation is keyword-only."""
    return f"{greeting}, {name}{punctuation}"

# ✅ Structural pattern matching (Python 3.10+)
def handle_response(response: dict):
    match response:
        case {"status": "ok", "data": data}:
            return process_data(data)
        case {"status": "error", "message": msg}:
            raise APIError(msg)
        case _:
            raise ValueError("Unknown response format")
```

---

## Review Checklist

### Type safety
- [ ] Functions have type annotations (parameters and return values)
- [ ] `Optional` makes it explicit when a value can be None
- [ ] Generic types are used correctly
- [ ] mypy passes (no errors)
- [ ] `Any` is avoided; where it is necessary, a comment explains why

### Async code
- [ ] async/await are paired correctly (no missing await)
- [ ] No blocking calls in async code
- [ ] `CancelledError` is handled correctly (clean up, then re-raise)
- [ ] Concurrent work uses `asyncio.gather` or `TaskGroup`
- [ ] Resources are cleaned up properly (async context managers)

### Exception handling
- [ ] Specific exception types are caught; no bare `except:`
- [ ] Exception chaining uses `from` to keep the cause
- [ ] Custom exceptions inherit from an appropriate base class
- [ ] Exception messages are meaningful and make debugging easier

### Data structures
- [ ] No mutable default arguments (list, dict, set)
- [ ] Class attributes are not mutable objects
- [ ] The right data structure is used (set vs list for lookups)
- [ ] Large datasets are processed with generators, not lists

### Testing
- [ ] Test coverage meets the target (≥80% recommended)
- [ ] Test names clearly describe the scenario under test
- [ ] Edge cases are covered by tests
- [ ] Mocks isolate external dependencies correctly
- [ ] Async code has matching async tests

### Code style
- [ ] Code follows the PEP 8 style guide
- [ ] Functions and classes have docstrings
- [ ] Imports are in the right order (standard library, third-party, local)
- [ ] Names are consistent and meaningful
- [ ] Modern Python features are used (f-strings, the walrus operator, etc.)

### Performance
- [ ] No repeated object creation inside loops
- [ ] String concatenation uses `join`
- [ ] Caching (`@lru_cache`) is used where it makes sense
- [ ] Parallelism fits the workload (threads for I/O-bound, processes for CPU-bound)
