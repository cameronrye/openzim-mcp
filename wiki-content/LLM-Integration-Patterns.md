# LLM Integration Patterns

Best practices and patterns for integrating OpenZIM MCP with Large Language Models.

## 🎯 Overview

OpenZIM MCP is specifically designed for LLM integration, providing intelligent, structured access to offline knowledge bases. This guide covers proven patterns and best practices for maximizing effectiveness.

## 🧠 Core Integration Principles

### 1. Progressive Discovery
Start broad, then narrow down based on results.

```
User: "Tell me about evolution"

LLM Strategy:
1. Search for "evolution" to get overview
2. Get article structure to understand scope
3. Extract specific sections based on user interest
4. Follow related links for deeper exploration
```

### 2. Context-Aware Retrieval
Use article structure and metadata to provide better context.

```
User: "What are the main mechanisms of evolution?"

LLM Strategy:
1. Get article structure for "Evolution"
2. Identify "Mechanisms" section
3. Retrieve that specific section
4. Extract related links for detailed mechanisms
```

### 3. Smart Fallback
Leverage the smart retrieval system for robust access.

```
# The system automatically handles:
- "Natural Selection" → "Natural_selection"
- "DNA Replication" → "DNA_replication"
- "Café" → "Caf%C3%A9"
```

## 🔍 Search Strategies

### Basic Search Pattern

```python
# 1. Start with broad search
search_results = search_zim_file(
    zim_file_path=zim_path,
    query="biology",
    limit=5
)

# 2. Get detailed content for relevant results
for result in search_results:
    content = get_zim_entry(
        zim_file_path=zim_path,
        entry_path=result.path
    )
```

### Advanced Search with Filters

```python
# Search within specific namespace
filtered_results = search_with_filters(
    zim_file_path=zim_path,
    query="evolution",
    namespace="C",  # Content articles only
    content_type="text/html",
    limit=10
)
```

### Auto-Complete for Better Queries

```python
# Get suggestions for partial queries
suggestions = get_search_suggestions(
    zim_file_path=zim_path,
    partial_query="bio",
    limit=5
)

# Use suggestions to refine search
for suggestion in suggestions:
    # Search using suggested terms
    pass
```

## 📄 Content Retrieval Patterns

### Structured Content Access

```python
# 1. Get article structure first
structure = get_article_structure(
    zim_file_path=zim_path,
    entry_path="C/Evolution"
)

# 2. Present overview to user
overview = f"Article '{structure.title}' has {len(structure.headings)} sections"

# 3. Get specific sections based on user interest
content = get_zim_entry(
    zim_file_path=zim_path,
    entry_path="C/Evolution",
    max_content_length=50000  # Adjust based on needs
)
```

### Link-Based Exploration

```python
# Extract links for related content
links = extract_article_links(
    zim_file_path=zim_path,
    entry_path="C/Biology"
)

# Categorize and present links
internal_links = links.internal_links
external_links = links.external_links
media_links = links.media_links
```

## 🎨 User Experience Patterns

### Conversational Knowledge Exploration

**Pattern**: Guide users through knowledge discovery

```
User: "I want to learn about biology"

LLM Response:
1. "I found several biology topics. Here are the main areas:"
2. Present structured overview from article structure
3. "Which area interests you most?"
4. Based on response, dive deeper into specific sections
```

### Research Assistant Pattern

**Pattern**: Help users research specific topics

```
User: "I'm writing about evolutionary mechanisms"

LLM Strategy:
1. Search for "evolutionary mechanisms"
2. Get article structure to identify key mechanisms
3. Extract content for each mechanism
4. Find related articles for additional context
5. Provide structured summary with sources
```

### Question-Answering Pattern

**Pattern**: Answer specific questions using knowledge base

```
User: "What is natural selection?"

LLM Strategy:
1. Search for "natural selection"
2. Get the main article content
3. Extract definition and key points
4. Provide concise answer with option to explore further
```

## 🔧 Performance Optimization Patterns

### Efficient Content Loading

```python
# Use appropriate content limits
small_preview = get_zim_entry(
    zim_file_path=zim_path,
    entry_path=article_path,
    max_content_length=5000  # For previews
)

full_content = get_zim_entry(
    zim_file_path=zim_path,
    entry_path=article_path,
    max_content_length=100000  # For full reading
)
```

### Batch Operations

```python
# Get multiple related articles efficiently
related_articles = ["C/Biology", "C/Evolution", "C/Genetics"]

for article in related_articles:
    # Process in sequence to leverage caching
    content = get_zim_entry(zim_file_path=zim_path, entry_path=article)
```

### Cache-Friendly Patterns

```python
# Reuse common queries to benefit from caching
popular_topics = ["Biology", "Physics", "Chemistry"]

for topic in popular_topics:
    # These will be cached for faster subsequent access
    search_zim_file(zim_file_path=zim_path, query=topic)
```

## 🎯 Specialized Use Cases

### Educational Content Delivery

```python
# Pattern for educational applications
def create_lesson_plan(topic):
    # 1. Get topic overview
    overview = search_zim_file(zim_path, topic, limit=1)

    # 2. Get article structure for curriculum planning
    structure = get_article_structure(zim_path, overview[0].path)

    # 3. Create progressive learning path
    sections = structure.sections

    # 4. Prepare related topics for exploration
    links = extract_article_links(zim_path, overview[0].path)

    return {
        "overview": overview,
        "structure": structure,
        "related_topics": links.internal_links
    }
```

### Research and Analysis

```python
# Pattern for research applications
def research_topic(topic, depth="medium"):
    results = []

    # 1. Initial search
    primary_results = search_zim_file(zim_path, topic, limit=10)

    # 2. Get detailed content
    for result in primary_results:
        content = get_zim_entry(zim_path, result.path)
        links = extract_article_links(zim_path, result.path)

        results.append({
            "content": content,
            "related": links.internal_links[:5]  # Top 5 related
        })

    # 3. Follow related links if deep research
    if depth == "deep":
        for result in results:
            for link in result["related"]:
                # Get related content
                pass

    return results
```

### Content Summarization

```python
# Pattern for summarization applications
def summarize_topic(topic):
    # 1. Get main article
    search_results = search_zim_file(zim_path, topic, limit=1)
    main_article = search_results[0]

    # 2. Get article structure for key points
    structure = get_article_structure(zim_path, main_article.path)

    # 3. Extract key sections
    key_sections = [s for s in structure.sections if s.level <= 2]

    # 4. Get content for each key section
    summary_content = []
    for section in key_sections:
        # Extract section content
        pass

    return {
        "title": structure.title,
        "key_points": key_sections,
        "word_count": structure.word_count,
        "summary": summary_content
    }
```

## 🔄 Error Handling Patterns

### Graceful Degradation

```python
def robust_content_access(entry_path):
    try:
        # Try direct access first
        return get_zim_entry(zim_path, entry_path)
    except EntryNotFound:
        # Fall back to search
        search_results = search_zim_file(zim_path, entry_path.split('/')[-1])
        if search_results:
            return get_zim_entry(zim_path, search_results[0].path)
        else:
            return None
```

### Progressive Content Loading

```python
def progressive_content_load(entry_path):
    # Start with structure
    structure = get_article_structure(zim_path, entry_path)

    # Get preview
    preview = get_zim_entry(zim_path, entry_path, max_content_length=2000)

    # Full content only if needed
    if user_wants_full_content:
        full_content = get_zim_entry(zim_path, entry_path, max_content_length=100000)
        return full_content

    return preview
```

## 📊 Monitoring and Analytics

### Performance Tracking

```python
# Monitor cache performance
health = get_server_health()
cache_hit_rate = health.cache.hit_rate

if cache_hit_rate < 0.7:
    # Adjust caching strategy
    pass
```

### Usage Analytics

```python
# Track popular content
popular_searches = track_search_patterns()
popular_articles = track_article_access()

# Optimize based on usage patterns
```

## 🎯 Best Practices Summary

### Do's ✅

1. **Start with search** before direct access
2. **Use article structure** to understand content organization
3. **Leverage caching** by reusing common queries
4. **Handle errors gracefully** with fallback strategies
5. **Monitor performance** and adjust limits accordingly
6. **Use appropriate content limits** for different use cases
7. **Extract links** for content discovery
8. **Provide progressive disclosure** of information

### Don'ts ❌

1. **Don't assume exact paths** - use smart retrieval
2. **Don't ignore article structure** - it provides valuable context
3. **Don't request excessive content** - use appropriate limits
4. **Don't ignore cache performance** - monitor and optimize
5. **Don't hardcode file paths** - make them configurable
6. **Don't skip error handling** - always have fallbacks
7. **Don't overwhelm users** - provide structured, digestible information

## 🚀 Advanced Integration Techniques

### Multi-ZIM Coordination

```python
# Pattern for working with multiple ZIM files
def search_across_zims(query, zim_files):
    all_results = []

    for zim_file in zim_files:
        results = search_zim_file(zim_file, query, limit=5)
        all_results.extend(results)

    # Deduplicate and rank results
    return deduplicate_and_rank(all_results)
```

### Contextual Content Assembly

```python
# Assemble content from multiple sources
def create_comprehensive_answer(topic):
    # Main article
    main_content = get_main_article(topic)

    # Related concepts
    related = get_related_articles(topic)

    # External context
    external_links = extract_external_links(main_content.path)

    return assemble_comprehensive_response(main_content, related, external_links)
```

---

**Ready to implement?** Check the [API Reference](API-Reference) for detailed tool documentation and the [Performance Optimization Guide](Performance-Optimization-Guide) for tuning recommendations.
