#!/usr/bin/env python3
"""
Simple validation script for the OpenZIM MCP website.
Checks for common issues like broken links, missing files, and HTML structure.
"""

import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

def check_file_exists(file_path):
    """Check if a file exists."""
    return Path(file_path).exists()

def validate_html_structure(html_content):
    """Basic HTML structure validation."""
    issues = []
    
    # Check for required meta tags
    required_meta = [
        'charset',
        'viewport',
        'description',
        'og:title',
        'og:description',
        'twitter:card'
    ]
    
    for meta in required_meta:
        if meta not in html_content:
            issues.append(f"Missing meta tag: {meta}")
    
    # Check for required sections
    required_sections = [
        'id="home"',
        'id="features"',
        'id="installation"',
        'id="usage"'
    ]
    
    for section in required_sections:
        if section not in html_content:
            issues.append(f"Missing section: {section}")
    
    # Check for navigation
    if 'class="navbar"' not in html_content:
        issues.append("Missing navigation bar")
    
    # Check for footer
    if 'class="footer"' not in html_content:
        issues.append("Missing footer")
    
    return issues

def validate_css_references(html_content, base_dir):
    """Check if CSS files referenced in HTML exist."""
    issues = []
    
    # Find CSS links
    css_pattern = r'<link[^>]*href=["\']([^"\']*\.css)["\']'
    css_files = re.findall(css_pattern, html_content)
    
    for css_file in css_files:
        if not css_file.startswith('http'):
            full_path = Path(base_dir) / css_file
            if not full_path.exists():
                issues.append(f"Missing CSS file: {css_file}")
    
    return issues

def validate_js_references(html_content, base_dir):
    """Check if JavaScript files referenced in HTML exist."""
    issues = []
    
    # Find JS scripts
    js_pattern = r'<script[^>]*src=["\']([^"\']*\.js)["\']'
    js_files = re.findall(js_pattern, html_content)
    
    for js_file in js_files:
        if not js_file.startswith('http'):
            full_path = Path(base_dir) / js_file
            if not full_path.exists():
                issues.append(f"Missing JavaScript file: {js_file}")
    
    return issues

def validate_image_references(html_content, base_dir):
    """Check if image files referenced in HTML exist."""
    issues = []
    
    # Find image sources
    img_pattern = r'(?:src|href)=["\']([^"\']*\.(png|jpg|jpeg|gif|svg|ico))["\']'
    img_files = re.findall(img_pattern, html_content)
    
    for img_file, ext in img_files:
        if not img_file.startswith('http'):
            full_path = Path(base_dir) / img_file
            if not full_path.exists():
                issues.append(f"Missing image file: {img_file}")
    
    return issues

def validate_internal_links(html_content):
    """Check for broken internal anchor links."""
    issues = []
    
    # Find internal links
    link_pattern = r'href=["\']#([^"\']*)["\']'
    anchor_links = re.findall(link_pattern, html_content)
    
    # Find IDs in the document
    id_pattern = r'id=["\']([^"\']*)["\']'
    ids = re.findall(id_pattern, html_content)
    
    for link in anchor_links:
        if link and link not in ids:
            issues.append(f"Broken internal link: #{link}")
    
    return issues

def main():
    """Main validation function."""
    website_dir = Path(__file__).parent
    html_file = website_dir / "index.html"
    
    if not html_file.exists():
        print("❌ index.html not found!")
        return False
    
    print("🔍 Validating OpenZIM MCP website...")
    print(f"📁 Website directory: {website_dir}")
    
    # Read HTML content
    with open(html_file, 'r', encoding='utf-8') as f:
        html_content = f.read()
    
    all_issues = []
    
    # Run validations
    print("\n📋 Running validations...")
    
    # HTML structure
    html_issues = validate_html_structure(html_content)
    all_issues.extend([f"HTML: {issue}" for issue in html_issues])
    
    # CSS references
    css_issues = validate_css_references(html_content, website_dir)
    all_issues.extend([f"CSS: {issue}" for issue in css_issues])
    
    # JavaScript references
    js_issues = validate_js_references(html_content, website_dir)
    all_issues.extend([f"JS: {issue}" for issue in js_issues])
    
    # Image references
    img_issues = validate_image_references(html_content, website_dir)
    all_issues.extend([f"IMG: {issue}" for issue in img_issues])
    
    # Internal links
    link_issues = validate_internal_links(html_content)
    all_issues.extend([f"LINK: {issue}" for issue in link_issues])
    
    # Report results
    print(f"\n📊 Validation Results:")
    print(f"   HTML structure checks: {len(html_issues)} issues")
    print(f"   CSS reference checks: {len(css_issues)} issues")
    print(f"   JavaScript reference checks: {len(js_issues)} issues")
    print(f"   Image reference checks: {len(img_issues)} issues")
    print(f"   Internal link checks: {len(link_issues)} issues")
    
    if all_issues:
        print(f"\n❌ Found {len(all_issues)} issues:")
        for issue in all_issues:
            print(f"   • {issue}")
        return False
    else:
        print("\n✅ All validations passed!")
        
        # Additional file checks
        print("\n📁 Checking required files:")
        required_files = [
            "assets/styles.css",
            "assets/script.js",
            "assets/favicon.svg",
            "assets/og-image.svg",
            "robots.txt",
            "sitemap.xml"
        ]
        
        missing_files = []
        for file_path in required_files:
            full_path = website_dir / file_path
            if full_path.exists():
                print(f"   ✅ {file_path}")
            else:
                print(f"   ❌ {file_path}")
                missing_files.append(file_path)
        
        if missing_files:
            print(f"\n⚠️  Missing {len(missing_files)} optional files")
            return True  # Still consider it a pass for core functionality
        else:
            print("\n🎉 All files present and website is ready!")
            return True

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
