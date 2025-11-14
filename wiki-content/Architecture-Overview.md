# Architecture Overview

Technical documentation of the OpenZIM MCP system architecture and design.

## System Architecture

OpenZIM MCP follows a modular, layered architecture designed for performance, security, and maintainability.

```
┌─────────────────────────────────────────────────────────────┐
│                    MCP Client Layer                        │
│              (Claude, Custom Clients, etc.)                │
└─────────────────────┬───────────────────────────────────────┘
                      │ MCP Protocol
┌─────────────────────▼───────────────────────────────────────┐
│                 OpenZIM MCP Server                         │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐   │
│  │   Server    │ │   Security  │ │   Instance Tracker  │   │
│  │   Core      │ │   Layer     │ │   & Health Monitor  │   │
│  └─────────────┘ └─────────────┘ └─────────────────────┘   │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                 Business Logic Layer                       │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐   │
│  │    Cache    │ │   Content   │ │    ZIM Operations   │   │
│  │   Manager   │ │  Processor  │ │  & Smart Retrieval  │   │
│  └─────────────┘ └─────────────┘ └─────────────────────┘   │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                   Data Access Layer                        │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐   │
│  │   libzim    │ │ File System │ │   Configuration     │   │
│  │  Interface  │ │   Access    │ │   & Validation      │   │
│  └─────────────┘ └─────────────┘ └─────────────────────┘   │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                 Storage Layer                              │
│        ZIM Files, Cache, Logs, Instance Tracking           │
└─────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Server Core (`server.py`)

**Responsibilities**:

- MCP protocol implementation
- Request routing and handling
- Tool registration and execution
- Error handling and response formatting

**Key Features**:

- Asynchronous request processing
- Structured logging
- Health monitoring
- Graceful shutdown handling

### 2. Security Layer (`security.py`)

**Responsibilities**:

- Input validation and sanitization
- Path traversal protection
- Access control enforcement
- Security policy implementation

**Security Features**:

- Whitelist-based directory access
- Path normalization and validation
- Input length limits
- File extension validation

### 3. Cache Manager (`cache.py`)

**Responsibilities**:

- LRU cache with TTL support
- Cache key generation and management
- Performance metrics collection
- Memory usage optimization

**Cache Strategy**:

- Content-based caching for search results
- Entry path mapping cache
- Metadata caching
- Configurable size and TTL limits

### 4. Content Processor (`content_processor.py`)

**Responsibilities**:

- HTML to text conversion
- Content formatting and cleanup
- Snippet generation
- Link extraction

**Processing Features**:

- Preserves formatting structure
- Handles various content types
- Configurable content limits
- Smart truncation

### 5. ZIM Operations (`zim_operations.py`)

**Responsibilities**:

- ZIM file access and management
- Search operations
- Entry retrieval
- Metadata extraction

**Smart Features**:

- Automatic path resolution
- Fallback search mechanisms
- Namespace browsing
- Article structure analysis

### 6. Instance Tracker (`instance_tracker.py`)

**Responsibilities**:

- Multi-instance management
- Conflict detection and resolution
- Process monitoring
- Configuration validation

**Enterprise Features**:

- Automatic instance registration
- Stale instance cleanup
- Configuration hash comparison
- Health monitoring integration

### 7. Smart Retrieval System

**Responsibilities**:

- Intelligent entry path resolution
- Path mapping cache management
- Automatic fallback strategies
- Performance optimization

**Advanced Capabilities**:

- Pattern learning and recognition
- Confidence-based caching
- Multiple search strategies
- Transparent operation

## Request Flow

### Typical Request Processing

```
1. MCP Client Request
   ↓
2. Server Core (request validation)
   ↓
3. Security Layer (authorization check)
   ↓
4. Cache Manager (cache lookup)
   ↓ (cache miss)
5. ZIM Operations (data retrieval)
   ↓
6. Content Processor (formatting)
   ↓
7. Cache Manager (cache storage)
   ↓
8. Server Core (response formatting)
   ↓
9. MCP Client Response
```

### Smart Retrieval Flow

```
1. Direct Entry Access Attempt
   ↓ (fails)
2. Search-Based Fallback
   ↓
3. Path Mapping Cache Check
   ↓ (miss)
4. Multiple Search Strategies
   ↓
5. Best Match Selection
   ↓
6. Path Mapping Cache Update
   ↓
7. Content Retrieval
```

## Module Structure

### Core Modules

```
openzim_mcp/
├── __init__.py          # Package initialization and version
├── __main__.py          # CLI entry point
├── main.py              # Application entry point
├── server.py            # MCP server implementation
├── config.py            # Configuration management
├── security.py          # Security and validation
├── cache.py             # Caching functionality
├── content_processor.py # Content processing
├── zim_operations.py    # ZIM file operations
├── instance_tracker.py  # Multi-instance management
├── exceptions.py        # Custom exceptions
└── constants.py         # Application constants
```

### Enhanced Module Responsibilities

#### Core Infrastructure

- **`server.py`**: Enhanced with health monitoring and diagnostics
- **`config.py`**: Expanded configuration with validation and profiles
- **`security.py`**: Advanced security features and input validation

#### Business Logic

- **`zim_operations.py`**: Smart retrieval system integration
- **`cache.py`**: Multi-layer caching with performance metrics
- **`content_processor.py`**: Enhanced content analysis and link extraction

#### Enterprise Features

- **`instance_tracker.py`**: Multi-instance management and conflict resolution
- **Smart Retrieval**: Integrated path resolution and fallback mechanisms
- **Health Monitoring**: Comprehensive system diagnostics and metrics

### Configuration System

```python
# Hierarchical configuration with validation
class OpenZimMcpConfig:
    cache: CacheConfig
    content: ContentConfig
    logging: LoggingConfig
    server: ServerConfig
    security: SecurityConfig
    instance: InstanceConfig
```

### Dependency Injection

```python
# Modular design with dependency injection
class OpenZimMcpServer:
    def __init__(
        self,
        config: OpenZimMcpConfig,
        cache_manager: CacheManager,
        content_processor: ContentProcessor,
        zim_operations: ZimOperations,
        security_validator: SecurityValidator,
        instance_tracker: InstanceTracker
    ):
        # Component initialization
```

## Design Patterns

### 1. Strategy Pattern

**Used for**: Content processing strategies

```python
class ContentProcessor:
    def __init__(self, strategies: Dict[str, ProcessingStrategy]):
        self.strategies = strategies

    def process(self, content_type: str, content: str) -> str:
        strategy = self.strategies.get(content_type, self.default_strategy)
        return strategy.process(content)
```

### 2. Factory Pattern

**Used for**: ZIM file handler creation

```python
class ZimHandlerFactory:
    @staticmethod
    def create_handler(zim_file_path: str) -> ZimHandler:
        # Create appropriate handler based on file characteristics
        return ZimHandler(zim_file_path)
```

### 3. Observer Pattern

**Used for**: Health monitoring and metrics

```python
class HealthMonitor:
    def __init__(self):
        self.observers = []

    def notify_health_change(self, health_data: HealthData):
        for observer in self.observers:
            observer.on_health_update(health_data)
```

### 4. Decorator Pattern

**Used for**: Caching and logging

```python
@cache_result(ttl=3600)
@log_performance
def search_zim_file(self, zim_file_path: str, query: str) -> List[SearchResult]:
    # Implementation
```

## Performance Architecture

### Caching Strategy

```
┌─────────────────────────────────────────────────────────────┐
│                    Cache Layers                            │
│                                                             │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐   │
│  │   L1 Cache  │ │   L2 Cache  │ │     L3 Cache        │   │
│  │  (Memory)   │ │ (Metadata)  │ │  (Path Mapping)     │   │
│  │             │ │             │ │                     │   │
│  │ • Search    │ │ • ZIM Meta  │ │ • Entry Paths       │   │
│  │ • Content   │ │ • Structure │ │ • Namespace Info    │   │
│  │ • Links     │ │ • Health    │ │ • Suggestions       │   │
│  └─────────────┘ └─────────────┘ └─────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Asynchronous Processing

```python
# Non-blocking operations for better performance
async def handle_request(self, request: McpRequest) -> McpResponse:
    # Asynchronous request processing
    result = await self.process_async(request)
    return self.format_response(result)
```

### Resource Management

```python
# Efficient resource cleanup
class ZimFileManager:
    def __init__(self):
        self.open_files = {}
        self.file_locks = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup_resources()
```

## Security Architecture

### Defense in Depth

```
┌─────────────────────────────────────────────────────────────┐
│                  Security Layers                           │
│                                                             │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐   │
│  │   Input     │ │    Path     │ │      Access         │   │
│  │ Validation  │ │ Validation  │ │     Control         │   │
│  │             │ │             │ │                     │   │
│  │ • Sanitize  │ │ • Normalize │ │ • Directory Limits  │   │
│  │ • Length    │ │ • Traversal │ │ • File Extensions   │   │
│  │ • Type      │ │ • Resolve   │ │ • Permission Check  │   │
│  └─────────────┘ └─────────────┘ └─────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Security Validation Pipeline

```python
def validate_request(self, request: McpRequest) -> ValidationResult:
    # 1. Input validation
    self.validate_input(request.params)

    # 2. Path validation
    self.validate_paths(request.file_paths)

    # 3. Access control
    self.check_access_permissions(request.file_paths)

    # 4. Rate limiting (future)
    self.check_rate_limits(request.client_id)

    return ValidationResult.VALID
```

## Monitoring and Observability

### Health Monitoring

```python
class HealthMonitor:
    def collect_metrics(self) -> HealthMetrics:
        return HealthMetrics(
            cache_performance=self.cache_manager.get_metrics(),
            memory_usage=self.get_memory_usage(),
            request_metrics=self.get_request_metrics(),
            instance_status=self.instance_tracker.get_status()
        )
```

### Structured Logging

```python
# Consistent logging structure
logger.info(
    "Request processed",
    extra={
        "request_id": request.id,
        "tool_name": request.tool,
        "duration_ms": duration,
        "cache_hit": cache_hit,
        "zim_file": zim_file_path
    }
)
```

## Multi-Instance Management

### Instance Tracking

```python
class InstanceTracker:
    def register_instance(self) -> InstanceInfo:
        instance = InstanceInfo(
            pid=os.getpid(),
            config_hash=self.config.get_hash(),
            start_time=datetime.now(),
            directories=self.config.allowed_directories
        )
        self.save_instance_file(instance)
        return instance
```

### Conflict Detection

```python
def detect_conflicts(self) -> List[Conflict]:
    conflicts = []
    active_instances = self.get_active_instances()

    for instance in active_instances:
        if self.has_config_conflict(instance):
            conflicts.append(ConfigConflict(instance))

        if self.has_directory_conflict(instance):
            conflicts.append(DirectoryConflict(instance))

    return conflicts
```

## Testing Architecture

### Test Structure

```
tests/
├── unit/                # Unit tests with mocks
├── integration/         # Integration tests with real ZIM files
├── security/           # Security and validation tests
├── performance/        # Performance and load tests
├── fixtures/           # Test data and fixtures
└── conftest.py         # Pytest configuration
```

### Test Categories

1. **Unit Tests**: Fast, isolated component testing
2. **Integration Tests**: End-to-end functionality with real ZIM files
3. **Security Tests**: Path traversal and input validation
4. **Performance Tests**: Cache performance and resource usage

## Scalability Considerations

### Horizontal Scaling

- **Multi-instance support**: Conflict detection and resolution
- **Load balancing**: Multiple server instances
- **Shared caching**: Future Redis integration

### Vertical Scaling

- **Memory optimization**: Efficient cache management
- **CPU optimization**: Asynchronous processing
- **I/O optimization**: Smart file access patterns

---

**Want to contribute?** Check the [Contributing Guidelines](https://github.com/cameronrye/openzim-mcp/blob/main/CONTRIBUTING.md) for development setup and coding standards.
