// Mobile Navigation Toggle
document.addEventListener('DOMContentLoaded', function() {
    const navToggle = document.getElementById('nav-toggle');
    const navMenu = document.getElementById('nav-menu');
    const navLinks = document.querySelectorAll('.nav-link');

    // Toggle mobile menu
    navToggle.addEventListener('click', function() {
        navToggle.classList.toggle('active');
        navMenu.classList.toggle('active');
        document.body.classList.toggle('nav-open');
    });

    // Close mobile menu when clicking on a link
    navLinks.forEach(link => {
        link.addEventListener('click', function() {
            navToggle.classList.remove('active');
            navMenu.classList.remove('active');
            document.body.classList.remove('nav-open');
        });
    });

    // Close mobile menu when clicking outside
    document.addEventListener('click', function(e) {
        if (!navToggle.contains(e.target) && !navMenu.contains(e.target)) {
            navToggle.classList.remove('active');
            navMenu.classList.remove('active');
            document.body.classList.remove('nav-open');
        }
    });
});

// Navbar scroll effect
window.addEventListener('scroll', function() {
    const navbar = document.getElementById('navbar');
    if (window.scrollY > 50) {
        navbar.style.background = 'rgba(255, 255, 255, 0.98)';
        navbar.style.boxShadow = '0 4px 6px -1px rgba(0, 0, 0, 0.1)';
    } else {
        navbar.style.background = 'rgba(255, 255, 255, 0.95)';
        navbar.style.boxShadow = 'none';
    }
});

// Smooth scrolling for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            const offsetTop = target.offsetTop - 80; // Account for fixed navbar
            window.scrollTo({
                top: offsetTop,
                behavior: 'smooth'
            });
        }
    });
});

// Copy to clipboard functionality
function initCopyButtons() {
    const copyButtons = document.querySelectorAll('.copy-btn');
    
    copyButtons.forEach(button => {
        button.addEventListener('click', async function() {
            const targetId = this.getAttribute('data-clipboard-target');
            const targetElement = document.querySelector(targetId);
            
            if (targetElement) {
                const text = targetElement.textContent || targetElement.innerText;
                
                try {
                    await navigator.clipboard.writeText(text);
                    
                    // Visual feedback
                    const originalIcon = this.querySelector('.copy-icon');
                    const originalText = originalIcon.textContent;
                    originalIcon.textContent = '✅';
                    
                    setTimeout(() => {
                        originalIcon.textContent = originalText;
                    }, 2000);
                    
                } catch (err) {
                    console.error('Failed to copy text: ', err);
                    
                    // Fallback for older browsers
                    const textArea = document.createElement('textarea');
                    textArea.value = text;
                    document.body.appendChild(textArea);
                    textArea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textArea);
                    
                    // Visual feedback
                    const originalIcon = this.querySelector('.copy-icon');
                    const originalText = originalIcon.textContent;
                    originalIcon.textContent = '✅';
                    
                    setTimeout(() => {
                        originalIcon.textContent = originalText;
                    }, 2000);
                }
            }
        });
    });
}

// Tab functionality for usage examples
function initTabs() {
    const tabButtons = document.querySelectorAll('.tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');
    
    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            const targetTab = this.getAttribute('data-tab');
            
            // Remove active class from all buttons and panes
            tabButtons.forEach(btn => btn.classList.remove('active'));
            tabPanes.forEach(pane => pane.classList.remove('active'));
            
            // Add active class to clicked button and corresponding pane
            this.classList.add('active');
            const targetPane = document.getElementById(targetTab);
            if (targetPane) {
                targetPane.classList.add('active');
            }
        });
    });
}

// Add more tab content dynamically
function addTabContent() {
    const tabContent = document.querySelector('.tab-content');
    
    // Browse tab content
    const browseTab = document.createElement('div');
    browseTab.className = 'tab-pane';
    browseTab.id = 'browse';
    browseTab.innerHTML = `
        <div class="example-block">
            <h4>Browse Namespaces</h4>
            <div class="code-block">
                <button class="copy-btn" data-clipboard-target="#browse-example">
                    <span class="copy-icon">📋</span>
                </button>
                <pre><code id="browse-example">{
  "name": "browse_namespace",
  "arguments": {
    "zim_file_path": "wikipedia_en_100_2025-08.zim",
    "namespace": "C",
    "limit": 10,
    "offset": 0
  }
}</code></pre>
            </div>
            <div class="example-result">
                <h5>Response:</h5>
                <pre><code>{
  "namespace": "C",
  "total_in_namespace": 80000,
  "offset": 0,
  "limit": 10,
  "returned_count": 10,
  "has_more": true,
  "entries": [
    {
      "path": "C/Biology",
      "title": "Biology",
      "content_type": "text/html",
      "preview": "Biology is the scientific study of life..."
    }
  ]
}</code></pre>
            </div>
        </div>
    `;
    
    // Structure tab content
    const structureTab = document.createElement('div');
    structureTab.className = 'tab-pane';
    structureTab.id = 'structure';
    structureTab.innerHTML = `
        <div class="example-block">
            <h4>Get Article Structure</h4>
            <div class="code-block">
                <button class="copy-btn" data-clipboard-target="#structure-example">
                    <span class="copy-icon">📋</span>
                </button>
                <pre><code id="structure-example">{
  "name": "get_article_structure",
  "arguments": {
    "zim_file_path": "wikipedia_en_100_2025-08.zim",
    "entry_path": "C/Evolution"
  }
}</code></pre>
            </div>
            <div class="example-result">
                <h5>Response:</h5>
                <pre><code>{
  "title": "Evolution",
  "path": "C/Evolution",
  "content_type": "text/html",
  "headings": [
    {"level": 1, "text": "Evolution", "id": "evolution"},
    {"level": 2, "text": "History", "id": "history"},
    {"level": 2, "text": "Mechanisms", "id": "mechanisms"}
  ],
  "sections": [
    {
      "title": "Evolution",
      "level": 1,
      "content_preview": "Evolution is the change in heritable traits...",
      "word_count": 150
    }
  ],
  "word_count": 5000
}</code></pre>
            </div>
        </div>
    `;
    
    // Config tab content
    const configTab = document.createElement('div');
    configTab.className = 'tab-pane';
    configTab.id = 'config';
    configTab.innerHTML = `
        <div class="example-block">
            <h4>MCP Client Configuration</h4>
            <div class="code-block">
                <button class="copy-btn" data-clipboard-target="#config-example">
                    <span class="copy-icon">📋</span>
                </button>
                <pre><code id="config-example">{
  "mcpServers": {
    "openzim-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/openzim-mcp",
        "run",
        "python",
        "-m",
        "openzim_mcp",
        "/path/to/zim/files"
      ]
    }
  }
}</code></pre>
            </div>
            <div class="example-result">
                <h5>Environment Variables (Optional):</h5>
                <pre><code># Cache configuration
export OPENZIM_MCP_CACHE__ENABLED=true
export OPENZIM_MCP_CACHE__MAX_SIZE=200
export OPENZIM_MCP_CACHE__TTL_SECONDS=7200

# Content configuration
export OPENZIM_MCP_CONTENT__MAX_CONTENT_LENGTH=200000
export OPENZIM_MCP_CONTENT__SNIPPET_LENGTH=2000

# Logging configuration
export OPENZIM_MCP_LOGGING__LEVEL=INFO</code></pre>
            </div>
        </div>
    `;
    
    tabContent.appendChild(browseTab);
    tabContent.appendChild(structureTab);
    tabContent.appendChild(configTab);
}

// Intersection Observer for animations
function initScrollAnimations() {
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };
    
    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.opacity = '1';
                entry.target.style.transform = 'translateY(0)';
            }
        });
    }, observerOptions);
    
    // Observe feature cards
    document.querySelectorAll('.feature-card').forEach(card => {
        card.style.opacity = '0';
        card.style.transform = 'translateY(20px)';
        card.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
        observer.observe(card);
    });
    
    // Observe installation steps
    document.querySelectorAll('.step').forEach(step => {
        step.style.opacity = '0';
        step.style.transform = 'translateY(20px)';
        step.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
        observer.observe(step);
    });
}

// Add keyboard navigation for tabs
function initKeyboardNavigation() {
    const tabButtons = document.querySelectorAll('.tab-btn');
    
    tabButtons.forEach((button, index) => {
        button.addEventListener('keydown', function(e) {
            let targetIndex;
            
            switch(e.key) {
                case 'ArrowLeft':
                    e.preventDefault();
                    targetIndex = index > 0 ? index - 1 : tabButtons.length - 1;
                    tabButtons[targetIndex].focus();
                    tabButtons[targetIndex].click();
                    break;
                case 'ArrowRight':
                    e.preventDefault();
                    targetIndex = index < tabButtons.length - 1 ? index + 1 : 0;
                    tabButtons[targetIndex].focus();
                    tabButtons[targetIndex].click();
                    break;
                case 'Home':
                    e.preventDefault();
                    tabButtons[0].focus();
                    tabButtons[0].click();
                    break;
                case 'End':
                    e.preventDefault();
                    tabButtons[tabButtons.length - 1].focus();
                    tabButtons[tabButtons.length - 1].click();
                    break;
            }
        });
    });
}

// Performance optimization: Lazy load images
function initLazyLoading() {
    const images = document.querySelectorAll('img[data-src]');
    
    const imageObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const img = entry.target;
                img.src = img.dataset.src;
                img.classList.remove('lazy');
                imageObserver.unobserve(img);
            }
        });
    });
    
    images.forEach(img => imageObserver.observe(img));
}

// Initialize all functionality when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initCopyButtons();
    initTabs();
    addTabContent();
    initScrollAnimations();
    initKeyboardNavigation();
    initLazyLoading();
    
    // Re-initialize copy buttons for dynamically added content
    setTimeout(() => {
        initCopyButtons();
    }, 100);
});

// Add some Easter eggs for developers
console.log(`
🧠 OpenZIM MCP - Intelligent Knowledge Access for AI Models

Thanks for checking out the console! 

If you're interested in contributing to OpenZIM MCP, 
check out our GitHub repository:
https://github.com/cameronrye/openzim-mcp

Built with ❤️ by the OpenZIM MCP Development Team
`);

// Add performance monitoring
if ('performance' in window) {
    window.addEventListener('load', function() {
        setTimeout(() => {
            const perfData = performance.getEntriesByType('navigation')[0];
            console.log('Page load performance:', {
                'DOM Content Loaded': Math.round(perfData.domContentLoadedEventEnd - perfData.domContentLoadedEventStart),
                'Load Complete': Math.round(perfData.loadEventEnd - perfData.loadEventStart),
                'Total Load Time': Math.round(perfData.loadEventEnd - perfData.fetchStart)
            });
        }, 0);
    });
}
