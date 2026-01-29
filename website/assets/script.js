// Theme Management
function initTheme() {
    const themeToggle = document.getElementById('theme-toggle');
    const html = document.documentElement;

    // Get saved theme or default to light
    const savedTheme = localStorage.getItem('theme') || 'light';
    html.setAttribute('data-theme', savedTheme);
    updateThemeIcon(savedTheme);

    // Theme toggle functionality
    themeToggle.addEventListener('click', function() {
        const currentTheme = html.getAttribute('data-theme');
        const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

        html.setAttribute('data-theme', newTheme);
        localStorage.setItem('theme', newTheme);
        updateThemeIcon(newTheme);

        // Add a subtle animation
        themeToggle.style.transform = 'scale(0.9)';
        setTimeout(() => {
            themeToggle.style.transform = 'scale(1)';
        }, 150);
    });

    function updateThemeIcon(theme) {
        const iconSvg = document.getElementById('theme-icon-svg');
        if (iconSvg) {
            if (theme === 'dark') {
                // Sun icon for dark mode (to switch to light)
                iconSvg.innerHTML = '<circle cx="12" cy="12" r="4"></circle><path d="M12 2v2"></path><path d="M12 20v2"></path><path d="m4.93 4.93 1.41 1.41"></path><path d="m17.66 17.66 1.41 1.41"></path><path d="M2 12h2"></path><path d="M20 12h2"></path><path d="m6.34 17.66-1.41 1.41"></path><path d="m19.07 4.93-1.41 1.41"></path>';
            } else {
                // Moon icon for light mode (to switch to dark)
                iconSvg.innerHTML = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>';
            }
        }
        themeToggle.setAttribute('aria-label',
            theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'
        );
    }
}

// Dynamic Version Fetching
async function fetchLatestVersion() {
    const versionDisplay = document.getElementById('version-display');
    const fallbackVersion = 'v0.5.1';

    // Show loading skeleton
    versionDisplay.classList.add('loading');
    versionDisplay.textContent = 'v0.0.0';

    try {
        // Check cache first
        const cached = localStorage.getItem('cached-version');
        if (cached) {
            const cacheData = JSON.parse(cached);
            const oneHour = 60 * 60 * 1000;

            if (Date.now() - cacheData.timestamp < oneHour) {
                versionDisplay.classList.remove('loading');
                versionDisplay.textContent = cacheData.version;
                return;
            }
        }

        const response = await fetch('https://api.github.com/repos/cameronrye/openzim-mcp/releases/latest', {
            headers: {
                'Accept': 'application/vnd.github.v3+json'
            }
        });

        if (!response.ok) throw new Error('Failed to fetch');

        const data = await response.json();
        const version = data.tag_name || fallbackVersion;

        // Remove loading state and show version
        versionDisplay.classList.remove('loading');
        versionDisplay.textContent = version;

        // Cache the version for 1 hour
        const cacheData = {
            version: version,
            timestamp: Date.now()
        };
        localStorage.setItem('cached-version', JSON.stringify(cacheData));

    } catch (error) {
        console.log('Using fallback version due to:', error.message);

        // Remove loading state and use fallback version
        versionDisplay.classList.remove('loading');
        versionDisplay.textContent = fallbackVersion;
    }
}

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

    // Keyboard navigation for mobile menu
    navToggle.addEventListener('keydown', function(e) {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            navToggle.click();
        }
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
    const theme = document.documentElement.getAttribute('data-theme') || 'light';

    if (window.scrollY > 50) {
        if (theme === 'dark') {
            navbar.style.background = 'rgba(15, 23, 42, 0.98)';
        } else {
            navbar.style.background = 'rgba(255, 255, 255, 0.98)';
        }
        navbar.style.boxShadow = '0 4px 6px -1px rgba(0, 0, 0, 0.1)';
    } else {
        if (theme === 'dark') {
            navbar.style.background = 'rgba(15, 23, 42, 0.95)';
        } else {
            navbar.style.background = 'rgba(255, 255, 255, 0.95)';
        }
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
    const clipboardSvg = '<span class="icon"><svg viewBox="0 0 24 24"><rect width="8" height="4" x="8" y="2" rx="1" ry="1"></rect><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"></path></svg></span>';
    const checkSvg = '<span class="icon"><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg></span>';

    copyButtons.forEach(button => {
        button.addEventListener('click', async function() {
            const targetId = this.getAttribute('data-clipboard-target');
            const targetElement = document.querySelector(targetId);

            if (targetElement) {
                const text = targetElement.textContent || targetElement.innerText;

                try {
                    await navigator.clipboard.writeText(text);

                    // Visual feedback - icon change
                    const originalIcon = this.querySelector('.copy-icon');
                    originalIcon.innerHTML = checkSvg;

                    // Show toast notification
                    showCopyToast();

                    setTimeout(() => {
                        originalIcon.innerHTML = clipboardSvg;
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

                    // Visual feedback - icon change
                    const originalIcon = this.querySelector('.copy-icon');
                    originalIcon.innerHTML = checkSvg;

                    // Show toast notification
                    showCopyToast();

                    setTimeout(() => {
                        originalIcon.innerHTML = clipboardSvg;
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

// Tab content is now in HTML, no need for dynamic generation

// Scroll Progress Indicator
function initScrollProgress() {
    const scrollProgress = document.getElementById('scroll-progress');
    if (!scrollProgress) return;

    function updateScrollProgress() {
        const scrollTop = window.scrollY;
        const docHeight = document.documentElement.scrollHeight - window.innerHeight;
        const scrollPercent = (scrollTop / docHeight) * 100;
        scrollProgress.style.width = scrollPercent + '%';
    }

    window.addEventListener('scroll', updateScrollProgress, { passive: true });
    updateScrollProgress();
}

// Back to Top Button
function initBackToTop() {
    const backToTop = document.getElementById('back-to-top');
    if (!backToTop) return;

    function toggleBackToTop() {
        if (window.scrollY > 500) {
            backToTop.classList.add('visible');
        } else {
            backToTop.classList.remove('visible');
        }
    }

    window.addEventListener('scroll', toggleBackToTop, { passive: true });

    backToTop.addEventListener('click', function() {
        window.scrollTo({
            top: 0,
            behavior: 'smooth'
        });
    });

    toggleBackToTop();
}

// Active Navigation Highlighting (Scroll Spy)
function initScrollSpy() {
    const sections = document.querySelectorAll('section[id]');
    const navLinks = document.querySelectorAll('.nav-link[href^="#"]');

    function updateActiveLink() {
        const scrollY = window.scrollY + 100;

        sections.forEach(section => {
            const sectionTop = section.offsetTop;
            const sectionHeight = section.offsetHeight;
            const sectionId = section.getAttribute('id');

            if (scrollY >= sectionTop && scrollY < sectionTop + sectionHeight) {
                navLinks.forEach(link => {
                    link.classList.remove('active');
                    if (link.getAttribute('href') === '#' + sectionId) {
                        link.classList.add('active');
                    }
                });
            }
        });
    }

    window.addEventListener('scroll', updateActiveLink, { passive: true });
    updateActiveLink();
}

// Copy Toast Notification
function showCopyToast() {
    const toast = document.getElementById('copy-toast');
    if (!toast) return;

    toast.classList.add('visible');
    setTimeout(() => {
        toast.classList.remove('visible');
    }, 2000);
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
    initTheme();
    fetchLatestVersion();
    initCopyButtons();
    initTabs();
    initScrollAnimations();
    initKeyboardNavigation();
    initLazyLoading();
    initScrollProgress();
    initBackToTop();
    initScrollSpy();
});

// Add some Easter eggs for developers
console.log(`
OpenZIM MCP - Intelligent Knowledge Access for AI Models

Thanks for checking out the console!

If you're interested in contributing to OpenZIM MCP,
check out our GitHub repository:
https://github.com/cameronrye/openzim-mcp

Built with care by Cameron Rye
`);

// Enhanced error handling for theme changes
function handleThemeChange() {
    const navbar = document.getElementById('navbar');
    if (navbar && window.scrollY > 50) {
        // Re-trigger scroll effect to update navbar background
        window.dispatchEvent(new Event('scroll'));
    }
}

// Listen for theme changes
document.addEventListener('DOMContentLoaded', function() {
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.type === 'attributes' && mutation.attributeName === 'data-theme') {
                handleThemeChange();
            }
        });
    });

    observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme']
    });
});

// Add performance monitoring
if ('performance' in window) {
    window.addEventListener('load', function() {
        setTimeout(() => {
            try {
                const perfData = performance.getEntriesByType('navigation')[0];
                if (perfData) {
                    console.log('Page load performance:', {
                        'DOM Content Loaded': Math.round(perfData.domContentLoadedEventEnd - perfData.domContentLoadedEventStart),
                        'Load Complete': Math.round(perfData.loadEventEnd - perfData.loadEventStart),
                        'Total Load Time': Math.round(perfData.loadEventEnd - perfData.fetchStart)
                    });
                }
            } catch (error) {
                console.log('Performance monitoring not available');
            }
        }, 0);
    });
}

// Add service worker registration for better caching (optional)
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        // Only register if we have a service worker file
        // This is commented out as we haven't created one yet
        // navigator.serviceWorker.register('/sw.js').catch(() => {});
    });
}
