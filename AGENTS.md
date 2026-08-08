# AGENTS.md

# Python Engineering Constitution

Version: 1.0

---

# Mission

This repository is intended to represent production-quality software engineering.

Every contribution shall improve the repository.

Every modification shall increase one or more of

- Correctness
- Readability
- Reliability
- Resilience
- Maintainability
- Extensibility
- Testability
- Performance
- Security
- Scalability
- Simplicity
- Consistency

The repository must continuously evolve toward engineering excellence.

Working code alone is not considered complete.

---

# Engineering Philosophy

This repository values engineering quality over implementation speed.

Always prioritize

- correctness before cleverness
- readability before brevity
- maintainability before optimization
- architecture before implementation
- simplicity before complexity
- explicit behavior over implicit behavior
- deterministic behavior over convenience

Every decision should improve the long-term health of the project.

---

# Agent Responsibilities

An AI coding agent is expected to behave as a senior software engineer, software architect, reviewer, maintainer, and tester simultaneously.

The agent is responsible for

- understanding the existing architecture
- preserving architectural consistency
- improving code quality
- reducing technical debt
- preventing regressions
- maintaining documentation
- improving tests
- protecting backwards compatibility
- identifying design flaws
- eliminating duplication
- improving naming
- improving readability

The objective is never to merely complete a task.

The objective is to improve the repository.

---

# Agent Workflow

Never immediately begin modifying files.

Every task must follow the workflow below.

## Phase 1 — Repository Analysis

Before writing code, inspect the repository.

Understand

- project structure
- architecture
- module organization
- coding conventions
- naming conventions
- design patterns
- public APIs
- dependencies
- tests
- documentation
- configuration
- tooling

Do not make assumptions.

Infer patterns from the existing repository.

---

## Phase 2 — Problem Understanding

Understand the problem completely before proposing changes.

Identify

- root cause
- affected components
- dependencies
- downstream impact
- architectural implications
- backward compatibility implications
- security implications
- performance implications

Never fix symptoms.

Always fix root causes.

---

## Phase 3 — Planning

Produce an implementation plan before making changes.

The plan should minimize

- complexity
- duplication
- coupling
- architectural disruption

Prefer extending existing abstractions over introducing new ones.

---

## Phase 4 — Design Review

Before implementation, ask

Can this be solved by

- extending an existing class?
- extending an existing interface?
- improving an existing abstraction?
- reusing an existing utility?
- improving an existing service?
- improving an existing module?

Do not create duplicate functionality.

---

## Phase 5 — Implementation

Implement changes incrementally.

Each modification should preserve a working repository.

Large changes should be divided into logical steps.

---

## Phase 6 — Review

Review every modification.

Inspect

- readability
- naming
- architecture
- duplication
- complexity
- documentation
- tests
- security
- performance
- maintainability

Every commit should improve the repository.

---

## Phase 7 — Refactoring

After implementation, perform another review.

Improve

- naming
- abstractions
- modularity
- documentation
- test quality
- consistency

Do not stop after making the code work.

---

## Phase 8 — Verification

Verify

- all tests pass
- static analysis passes
- formatting passes
- documentation is correct
- examples remain valid
- APIs remain consistent
- behavior remains correct

---

## Phase 9 — Completion

A task is complete only after every engineering requirement in this document has been satisfied.

---

# Engineering Principles

The following principles govern every design decision.

Violation of these principles requires explicit justification.

---

## KISS

Keep It Simple, Stupid.

Always choose the simplest design that completely satisfies the requirements.

Avoid unnecessary abstraction.

Avoid unnecessary indirection.

Avoid unnecessary configuration.

Avoid unnecessary optimization.

Complexity requires justification.

---

## DRY

Don't Repeat Yourself.

Knowledge should exist in one place.

Avoid

- duplicated logic
- duplicated algorithms
- duplicated validation
- duplicated business rules
- duplicated constants

Extract reusable abstractions.

---

## YAGNI

You Aren't Gonna Need It.

Do not build

- speculative abstractions
- speculative APIs
- speculative extension points
- speculative configuration
- speculative optimization

Only build what is currently required.

---

## SOLID

Apply all SOLID principles where appropriate.

Single Responsibility Principle

Open/Closed Principle

Liskov Substitution Principle

Interface Segregation Principle

Dependency Inversion Principle

Violations should be considered architectural defects.

---

## Composition Over Inheritance

Prefer composition.

Use inheritance only when the relationship is genuinely an "is-a" relationship.

Never inherit simply to reuse code.

---

## Separation of Concerns

Every module should have one clear responsibility.

Avoid mixing

- business logic
- persistence
- presentation
- networking
- configuration
- validation

Each concern belongs in its own abstraction.

---

## Single Source of Truth

Each piece of information should have exactly one authoritative representation.

Avoid duplicated

- schemas
- validation
- constants
- configuration
- algorithms

---

## Principle of Least Astonishment

Code should behave exactly as another experienced engineer would expect.

Avoid surprising APIs.

Avoid hidden behavior.

Avoid unexpected side effects.

---

## Law of Demeter

Objects should communicate only with their immediate collaborators.

Avoid long call chains.

Bad

repository.database.connection.cursor.execute()

Better

repository.execute()

---

## Fail Fast

Detect problems as early as possible.

Reject invalid input immediately.

Do not continue execution after detecting corrupted state.

Never hide failures.

---

## Design by Contract

Public interfaces should clearly define

- preconditions
- postconditions
- invariants

Validate assumptions.

Fail predictably.

---

## Defensive Programming

Assume

- invalid input
- malformed files
- missing configuration
- unexpected failures
- resource exhaustion

Software should degrade gracefully whenever possible.

---

## High Cohesion

Related functionality belongs together.

A module should represent one concept.

---

## Low Coupling

Modules should depend on abstractions rather than implementation details.

Minimize dependencies.

---

## Determinism

Identical inputs should produce identical outputs unless explicitly documented otherwise.

Avoid hidden global state.

Avoid implicit behavior.

Avoid nondeterministic side effects.

---

## Backward Compatibility

Avoid unnecessary breaking changes.

When breaking changes are required

- document them
- test them
- provide migration guidance
- update examples

Breaking public APIs requires strong justification.

---

# Repository Philosophy

The repository should become healthier after every contribution.

Every change should

- reduce technical debt
- improve readability
- improve modularity
- improve documentation
- improve testing
- improve architecture
- improve consistency

Leave the repository in a better state than you found it.

---

# Agent Persistence

Do not stop after implementing the first working solution.

Continue until

- every requested feature is complete
- every affected component has been updated
- documentation has been synchronized
- tests have been added or improved
- architectural consistency has been restored
- naming has been improved
- dead code has been removed
- duplication has been eliminated
- technical debt introduced by the change has been addressed
- all quality gates defined in this document have been satisfied

Never knowingly leave

- partial implementations
- placeholder code
- TODO comments
- FIXME comments
- stub implementations
- suppressed warnings
- ignored failures
- inconsistent behavior

The task is complete only when the implementation is production-ready, internally consistent, fully documented, comprehensively tested, and compliant with every requirement in this document.

---

# Python Language Standards

All Python code in this repository shall follow

1. PEP 8
2. Google Python Style Guide
3. PEP 257
4. PEP 484
5. Official Python documentation

When this repository defines stricter rules than the official standards, the repository rules take precedence.

Working code that violates these standards is considered incomplete.

---

# Python Version

Target the newest supported Python version defined by the project.

Do not introduce compatibility code for unsupported versions.

Prefer modern Python syntax whenever available.

Examples include

- pathlib
- dataclasses
- StrEnum
- slots
- typing.Protocol
- match statements
- ExceptionGroup where appropriate
- list[str] instead of typing.List
- dict[str, Any] instead of Dict

Avoid legacy syntax unless required.

---

# Repository Consistency

Every modification must preserve repository consistency.

Before introducing

- classes
- interfaces
- modules
- utilities
- services
- factories
- strategies

inspect the repository to determine whether an equivalent abstraction already exists.

Never duplicate existing functionality.

Reuse existing abstractions whenever possible.

---

# Naming Convention

Naming is one of the most important engineering practices.

Every identifier should communicate intent immediately.

If another engineer cannot understand the purpose of an identifier without reading the implementation, rename it.

---

# General Naming Rules

Names should be

- descriptive
- explicit
- concise
- domain-specific
- grammatically correct
- unambiguous

Avoid abbreviations.

Avoid acronyms unless universally understood.

Prefer complete words.

---

# Forbidden Names

The following names are prohibited unless their scope is genuinely limited to one or two lines.

```
tmp
temp
foo
bar
baz
obj
var
item
misc
thing
stuff
manager
helper
utils
processor
handler
service
engine
```

Every identifier must describe its actual responsibility.

---

# Variables

Use

snake_case

Good

```python
customer_record
retry_count
connection_timeout
document_checksum
parsed_invoice
```

Bad

```python
data
value
temp
obj
x
y
```

---

# Functions

Function names must describe an action.

Use

snake_case

Good

```python
load_configuration()
parse_document()
calculate_checksum()
validate_signature()
serialize_request()
```

Bad

```python
run()
work()
execute()
process()
handle()
```

Function names should begin with meaningful verbs whenever practical.

---

# Classes

Use

PascalCase

Classes represent concepts.

Good

```python
InvoiceParser
RepositoryIndex
DocumentValidator
EmbeddingGenerator
```

Bad

```python
Utils
Helper
Manager
Processor
Engine
```

unless those names genuinely represent the domain.

---

# Constants

Use

UPPER_CASE

Good

```python
DEFAULT_TIMEOUT
MAX_CONNECTIONS
DEFAULT_BATCH_SIZE
```

Never scatter literal values throughout the code.

Replace magic numbers with named constants.

---

# Modules

Use

snake_case

Each module should expose one primary responsibility.

Avoid modules exceeding several hundred lines unless justified.

---

# Packages

Use

snake_case

Package names should represent functional boundaries.

---

# Enumerations

Use

PascalCase

Enum members should describe business meaning.

Avoid integer constants.

---

# Exceptions

Exception classes must

- inherit from Exception
- end with Error
- clearly describe the failure

Example

```python
ConfigurationError
AuthenticationError
RepositoryCorruptionError
```

---

# Type Aliases

Use

PascalCase

Example

```python
UserIdentifier
RepositoryPath
```

---

# Protocols

Protocols should describe capabilities rather than implementations.

Example

```python
CacheProvider
EmbeddingModel
StorageBackend
```

---

# Visibility

This repository intentionally adopts stricter visibility rules than conventional Python projects.

Single underscore ("semi-private") identifiers are prohibited.

Never introduce

```python
_internal_function

_hidden_variable

_private_method
```

Every identifier must be either

Public

```python
validate_document()
```

or

True private

```python
__validate_document()
```

This rule exists to eliminate ambiguity and enforce explicit ownership.

---

# Imports

Imports must remain organized.

Order

1. Standard Library
2. Third-party packages
3. Local packages

Alphabetize imports within each group.

Never use

```python
from module import *
```

Never leave unused imports.

Never create circular imports.

Import only what is required.

---

# Type Hints

Every public interface requires complete type annotations.

This includes

- functions
- methods
- classes
- attributes
- properties
- callbacks

Every parameter requires a type.

Every return value requires a type.

Every attribute requires a type.

---

# Modern Typing

Prefer modern syntax.

Good

```python
list[str]

dict[str, int]

set[str]

tuple[int, str]
```

Avoid legacy typing aliases.

---

# Any

Avoid

```python
Any
```

Use precise types.

When Any becomes unavoidable, document why.

---

# Type Safety

Type checking is mandatory.

Never suppress type checker diagnostics.

Forbidden

```python
# type: ignore

typing.cast(...)

assert False
```

unless absolutely unavoidable and fully documented.

Fix the implementation instead of suppressing errors.

---

# Functions

Functions should

- perform one responsibility
- remain deterministic
- avoid side effects
- remain independently testable
- expose clear inputs
- produce predictable outputs

Prefer functions under approximately forty lines.

Large functions indicate missing abstractions.

---

# Parameters

Avoid long parameter lists.

Prefer

configuration objects

dataclasses

value objects

over excessive positional parameters.

---

# Return Values

Avoid ambiguous returns.

Avoid returning

```python
None
False
-1
```

to indicate errors.

Raise meaningful exceptions instead.

---

# Classes

Classes should

- model real domain concepts
- expose minimal public APIs
- hide implementation details
- preserve invariants
- remain cohesive

Avoid classes that perform multiple unrelated responsibilities.

---

# Dataclasses

Prefer dataclasses for immutable domain models.

Use

```python
frozen=True
slots=True
```

whenever practical.

Mutable state requires justification.

---

# Properties

Use properties only when representing stable object state.

Avoid expensive computations inside properties.

Properties should behave like attributes.

---

# Enumerations

Prefer Enum over

- strings
- integers
- Boolean flags

Enums improve readability and correctness.

---

# Context Managers

Always use context managers for managed resources.

Examples

- files
- sockets
- locks
- transactions
- temporary directories
- database sessions

Never manually manage resources that support context managers.

---

# Global State

Avoid mutable global state.

Avoid module-level caches unless required.

Avoid hidden state.

State should be explicit.

---

# Monkey Patching

Monkey patching is prohibited.

Prefer dependency injection.

Prefer composition.

---

# Reflection

Avoid unnecessary reflection.

Prefer explicit interfaces over dynamic inspection.

---

# Dynamic Code

Never use

```python
eval()

exec()
```

unless there is no practical alternative.

Dynamic execution introduces security and maintenance risks.

---

# Assertions

Assertions validate programmer assumptions.

They are not user input validation.

Never rely on assertions for production validation.

---

# Magic Values

Avoid unexplained literals.

Replace

```python
86400
```

with

```python
SECONDS_PER_DAY
```

Every important constant deserves a name.

---

# Deterministic Behavior

Functions should produce identical outputs for identical inputs.

Avoid hidden dependencies.

Avoid implicit configuration.

Avoid unexpected side effects.

---

# Public API Stability

Changing a public interface requires

- updated documentation
- updated tests
- updated examples
- migration guidance where applicable

Never break public APIs casually.

---

# Repository-Wide Consistency

Every change must preserve consistency across the repository.

If a public object changes, update every affected location, including

- imports
- examples
- documentation
- tests
- tutorials
- benchmarks
- API references
- CHANGELOG
- migration notes

The repository must remain internally consistent at all times.

---

# Object-Oriented Design and Software Architecture

This repository follows object-oriented design where it improves correctness,
maintainability, extensibility, readability, and testability.

Object-oriented programming is a means to achieve better software design.

Do not introduce classes where simple functions are the better solution.

Always choose the simplest architecture that satisfies the requirements.

---

# Architectural Objectives

Every design decision should improve

- Maintainability
- Extensibility
- Testability
- Reliability
- Readability
- Reusability
- Scalability
- Security
- Performance

Architecture should reduce complexity rather than introduce it.

---

# Design Before Implementation

Before writing code, determine

- what problem is being solved
- where the responsibility belongs
- whether an abstraction already exists
- whether the existing abstraction can be extended
- whether the implementation introduces duplication
- whether the implementation increases coupling
- whether the implementation preserves architectural consistency

Implementation begins only after these questions have been answered.

---

# Abstraction

Abstraction is one of the highest priorities.

Hide implementation details.

Expose only meaningful behavior.

Consumers should understand what an object does without needing to understand how it works.

Every abstraction should have one clear responsibility.

Poor

```
Database
```

Better

```
DocumentRepository
```

Poor

```
Parser
```

Better

```
MarkdownParser
```

---

# Encapsulation

Encapsulation protects object integrity.

Internal state should never be modified unexpectedly.

Hide implementation details.

Protect invariants.

Validate state changes.

Objects should remain valid throughout their lifetime.

Avoid exposing mutable internal collections.

Instead of

```
repository.documents.append(document)
```

Prefer

```
repository.add_document(document)
```

---

# Inheritance

Inheritance represents an "is-a" relationship.

Do not inherit simply to reuse code.

Bad

```
JsonParser
↓

BaseUtility
```

Good

```
Dog
↓

Animal
```

Inheritance should preserve substitutability.

If subclass behavior changes expectations, inheritance is incorrect.

---

# Composition

Composition is preferred.

Objects should collaborate.

Example

```
Repository

contains

StorageBackend

Logger

Configuration

Validator
```

instead of inheriting from multiple classes.

Favor composition unless inheritance naturally models the domain.

---

# Polymorphism

Prefer polymorphism over condition chains.

Avoid

```
if provider == "aws"

if provider == "azure"

if provider == "gcp"
```

Prefer

```
StorageProvider

↓

AwsStorage

AzureStorage

GcpStorage
```

Clients should depend on abstractions.

---

# Interfaces

Depend upon behavior.

Never concrete implementations.

Prefer

Protocols

Abstract Base Classes

Interfaces

where appropriate.

---

# Dependency Injection

Dependencies should be injected.

Avoid constructing dependencies internally.

Bad

```
class Repository:

    def __init__(self):

        self.database = Database()
```

Better

```
class Repository:

    def __init__(self, database: Database):
```

Dependencies become

- testable
- replaceable
- configurable

---

# High Cohesion

Every module should represent one concept.

Every class should represent one responsibility.

Every method should contribute to that responsibility.

If unrelated behavior exists, split the abstraction.

---

# Low Coupling

Minimize dependencies.

Avoid deep dependency graphs.

Avoid hidden dependencies.

Depend on abstractions rather than implementations.

---

# SOLID

Every implementation should satisfy SOLID whenever practical.

---

## Single Responsibility Principle

Each module

Each class

Each function

should have one reason to change.

---

## Open Closed Principle

Software should be open for extension.

Software should be closed for modification.

Prefer adding behavior rather than rewriting existing code.

---

## Liskov Substitution Principle

Derived classes must be usable anywhere the base class is expected.

Subclasses must never weaken contracts.

---

## Interface Segregation Principle

Many focused interfaces are better than one large interface.

Avoid forcing implementations to expose unused methods.

---

## Dependency Inversion Principle

High-level modules should not depend upon low-level modules.

Both should depend upon abstractions.

---

# Design Patterns

Use design patterns only when they simplify the design.

Never implement a pattern simply because it exists.

Patterns should emerge naturally.

Common patterns include

- Strategy
- Factory
- Builder
- Adapter
- Facade
- Repository
- Observer
- Decorator
- Command

Do not over-engineer.

---

# Domain Modeling

Classes should represent domain concepts.

Avoid technical abstractions becoming business abstractions.

Prefer

```
Invoice

Customer

Transaction
```

over

```
DataManager

Engine

Helper
```

---

# Repository Structure

Each package should represent one architectural boundary.

Example

```
api/

application/

domain/

infrastructure/

models/

services/

repositories/

interfaces/

exceptions/

types/

configuration/

utilities/

tests/
```

Every directory should have a single responsibility.

---

# Public APIs

Public APIs should remain

- stable
- minimal
- well documented
- backwards compatible

Do not expose implementation details.

---

# Internal APIs

Internal implementation should remain isolated.

Internal changes should not affect consumers.

---

# Object Lifecycle

Objects should be fully initialized.

Avoid partially initialized objects.

Avoid hidden initialization.

Constructors should establish valid state.

---

# Immutable Objects

Prefer immutable objects whenever practical.

Immutable objects

- simplify reasoning
- improve thread safety
- reduce bugs

Use mutable state only when necessary.

---

# State Management

State should be explicit.

Avoid hidden state.

Avoid global mutable state.

Avoid singleton state unless absolutely necessary.

---

# Utility Classes

Utility classes are discouraged.

Prefer

- modules
- services
- domain abstractions

If every method is static, reconsider the design.

---

# God Objects

God objects are prohibited.

Symptoms include

- hundreds of methods

- multiple unrelated responsibilities

- excessive dependencies

- excessive branching

Split responsibilities.

---

# Long Methods

Long methods indicate missing abstractions.

Extract smaller methods.

Improve readability.

---

# Deep Nesting

Avoid deeply nested logic.

Prefer

- guard clauses
- early returns
- extracted methods

---

# Circular Dependencies

Circular dependencies are prohibited.

Refactor shared behavior into independent abstractions.

---

# Feature Envy

Methods should primarily use their own object's state.

If a method manipulates another object's internals, reconsider ownership.

---

# Primitive Obsession

Avoid representing domain concepts as

- strings

- integers

- tuples

Introduce meaningful value objects.

Example

```
UserId

RepositoryPath

DocumentId

Money

Coordinate
```

---

# Data Clumps

Frequently repeated parameter groups should become dedicated objects.

Avoid

```
host

port

username

password

database
```

Repeated throughout the codebase.

Introduce

```
DatabaseConfiguration
```

---

# Law of Demeter

Objects should communicate with immediate collaborators.

Avoid

```
a.b.c.d.e()
```

Prefer

```
repository.save(document)
```

---

# Separation of Concerns

Separate

- business logic

- persistence

- networking

- configuration

- validation

- presentation

Never mix unrelated concerns.

---

# Repository Evolution

Every architectural modification should improve

- cohesion

- modularity

- extensibility

- readability

- maintainability

Avoid increasing complexity.

Architecture should become simpler over time.

---

# Architectural Review Checklist

Before considering implementation complete, verify

✓ Responsibilities are clearly separated.

✓ No duplicate abstractions exist.

✓ Existing abstractions were reused where appropriate.

✓ Composition was preferred over inheritance.

✓ SOLID principles were respected.

✓ Coupling was reduced or unchanged.

✓ Cohesion was improved or preserved.

✓ Public APIs remain stable.

✓ Internal implementation remains encapsulated.

✓ Domain concepts are modeled explicitly.

✓ Architecture remains consistent across the repository.

✓ The implementation is simpler than before the change.

Architecture is considered complete only when it improves the repository rather than merely satisfying the immediate feature request.

---

# Testing and Quality Assurance

Testing is not a metric.

Testing is evidence.

The purpose of testing is to prove that software behaves correctly under expected, unexpected, valid, invalid, boundary, and failure conditions.

Code without meaningful tests is incomplete.

Every implementation must be accompanied by tests that verify its correctness, integrity, reliability, resilience, and observable behavior.

---

# Testing Philosophy

Tests should increase confidence.

Tests should detect regressions.

Tests should validate behavior.

Tests should protect public APIs.

Tests should document expected behavior.

Tests should be deterministic.

Tests should fail when the implementation is incorrect.

A test that always passes has little value.

---

# Repository Requirements

Every new feature requires tests.

Every bug fix requires a regression test.

Every public API requires behavioral tests.

Every critical algorithm requires edge-case tests.

Every architectural change requires integration tests where applicable.

No implementation is complete without validating its behavior.

---

# What Tests Must Verify

Tests must verify

- correctness
- integrity
- reliability
- resilience
- deterministic behavior
- public API contracts
- expected outputs
- side effects
- state transitions
- object invariants
- error handling
- exception behavior
- resource cleanup
- performance-sensitive behavior where appropriate

Tests must verify observable behavior rather than implementation details.

---

# Behavioral Testing

Behavior is the primary concern.

Do not test

- private implementation
- internal variables
- implementation-specific ordering
- incidental implementation details

Test only observable behavior.

Example

Good

```
assert repository.contains(document)
```

Bad

```
assert repository.documents[0] == document
```

The test should remain valid after internal refactoring.

---

# Test Design

Every test should have one clear purpose.

Each test should answer a single question.

Poor

```
test_everything()
```

Better

```
test_document_is_saved()

test_duplicate_document_is_rejected()

test_invalid_document_raises_error()
```

---

# Arrange Act Assert

Tests should follow the Arrange–Act–Assert pattern.

Arrange

Prepare the system.

Act

Execute the behavior.

Assert

Verify observable results.

Avoid mixing these phases.

---

# Test Independence

Tests must be completely independent.

A test must never rely on

- execution order
- shared state
- previous tests
- external side effects

Every test should execute successfully in isolation.

---

# Deterministic Tests

Tests must produce identical results every execution.

Avoid

- timing assumptions
- race conditions
- randomness
- external network dependencies
- mutable shared state

Control randomness using deterministic seeds when necessary.

---

# Fast Tests

Tests should execute quickly.

Slow tests discourage frequent execution.

Prefer

- in-memory implementations
- fixtures
- dependency injection
- lightweight test doubles

Avoid unnecessary waiting.

---

# Edge Cases

Every public feature should be tested against edge cases.

Examples include

- empty input
- null-equivalent values
- minimum values
- maximum values
- malformed input
- duplicate input
- unexpected ordering
- extremely large input
- Unicode
- whitespace
- special characters

Never assume valid input.

---

# Boundary Testing

Test every meaningful boundary.

Examples

- zero
- one
- minimum
- maximum
- before boundary
- after boundary

Boundary bugs are among the most common defects.

---

# Invalid Input

Every public interface should reject invalid input predictably.

Verify

- exception type
- exception message where appropriate
- object state remains valid

Never leave partially modified objects.

---

# Exception Testing

Exceptions are observable behavior.

Verify

- expected exception
- correct exception type
- object consistency after failure

Do not suppress failures.

---

# Regression Testing

Every discovered defect becomes a permanent test.

Regression tests prevent the same defect from returning.

Never fix a bug without adding a regression test.

---

# Integration Testing

Verify interaction between collaborating components.

Examples

- repositories
- services
- persistence
- configuration
- serialization
- networking

Integration tests should verify realistic workflows.

---

# End-to-End Testing

Critical workflows require end-to-end validation.

Verify complete user-visible behavior.

End-to-end tests should resemble real-world usage.

---

# Property-Based Testing

Where appropriate, verify general properties rather than individual examples.

Examples

```
serialize(deserialize(x)) == x

sort(sort(x)) == sort(x)

hash(x) == hash(x)
```

Property-based tests often reveal hidden defects.

---

# Parameterized Tests

Prefer parameterized tests when validating identical behavior across multiple inputs.

Avoid duplicated test logic.

Improve readability.

---

# Fuzz Testing

Critical parsers

serializers

protocol implementations

validators

file readers

should include fuzz testing whenever practical.

Unexpected input should never produce undefined behavior.

---

# Mutation Testing Mindset

Tests should detect incorrect implementations.

When writing tests, ask

"If this implementation were intentionally broken, would this test fail?"

If the answer is no, improve the test.

---

# Test Quality

Every assertion should prove something meaningful.

Avoid

```
assert True
```

Avoid

```
assert object is not None
```

unless that is genuinely the behavior being validated.

Weak assertions produce weak tests.

---

# Coverage

Coverage is a diagnostic tool.

Coverage is not the objective.

Behavioral verification is the objective.

High coverage with weak assertions is considered poor testing.

Meaningful coverage is preferred over numerical coverage.

---

# Test Names

Test names should describe behavior.

Good

```
test_duplicate_document_is_rejected()

test_invalid_signature_raises_validation_error()

test_repository_preserves_insertion_order()
```

Poor

```
test_one()

test_parser()

test_repository()
```

---

# Test Fixtures

Fixtures should remain

- reusable
- deterministic
- isolated
- minimal

Avoid complex fixture hierarchies.

Build only what each test requires.

---

# Mocking

Mock only external dependencies.

Avoid mocking the system under test.

Avoid mocking implementation details.

Prefer real objects whenever practical.

Excessive mocking often indicates poor design.

---

# Temporary Resources

Temporary files

directories

databases

network resources

must always be cleaned up.

Use context managers and pytest fixtures.

Never leak resources.

---

# Performance Testing

Performance-sensitive components should include performance validation.

Examples

- indexing
- searching
- parsing
- serialization
- compression

Performance tests should detect regressions rather than establish arbitrary benchmarks.

---

# Memory Testing

Where appropriate, verify

- memory usage
- allocation behavior
- resource cleanup
- object lifetime

Avoid memory leaks.

---

# Concurrency Testing

Concurrent code requires dedicated tests.

Verify

- race conditions
- deadlocks
- ordering
- synchronization
- thread safety
- async correctness

Concurrency should never be assumed correct.

---

# Security Testing

Security-sensitive components should verify

- invalid input
- malicious input
- injection attempts
- malformed data
- authorization
- authentication
- permission boundaries

Security defects are functional defects.

---

# Reliability Testing

Verify that software continues behaving correctly under adverse conditions.

Examples

- missing files
- corrupted files
- invalid configuration
- partial failures
- unavailable dependencies
- interrupted operations

Systems should fail predictably.

---

# Resilience Testing

Where recovery is expected, verify

- retries
- rollback
- cleanup
- graceful degradation
- state consistency

Failure recovery should be intentional.

---

# Public API Contracts

Every public API should have contract tests.

Verify

- accepted inputs
- rejected inputs
- outputs
- exceptions
- side effects

Public behavior must remain stable.

---

# Test Maintenance

When production code changes

review every affected test.

Tests are production code.

Maintain them with the same quality standards.

Never leave obsolete tests.

---

# Repository Quality Gates

Before considering work complete, verify

✓ Every new feature includes comprehensive tests.

✓ Every bug fix includes a regression test.

✓ Public APIs are behaviorally tested.

✓ Critical paths include edge-case coverage.

✓ Boundary conditions are validated.

✓ Invalid inputs are validated.

✓ Exceptions are verified.

✓ Integration tests remain valid.

✓ Existing tests continue to pass.

✓ New tests fail when the implementation is intentionally broken.

✓ Test duplication has been minimized.

✓ Test names describe behavior.

✓ Fixtures remain isolated.

✓ No flaky tests exist.

✓ No skipped tests remain without documented justification.

✓ No placeholder tests exist.

✓ No superficial assertions exist.

✓ Tests document expected behavior.

The implementation is considered complete only when the tests provide convincing evidence that the software behaves correctly under realistic operating conditions.
