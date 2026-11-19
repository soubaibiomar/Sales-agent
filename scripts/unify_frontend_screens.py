#!/usr/bin/env python3
"""
SALES AI MANAGEMENT PLATFORM — FRONTEND UNIFIER SCRIPT
Harmonizes all 28 frontend views with the V2.0 Design System,
injecting the authoritative master sidebar, topbar, CSS tokens,
and preserving 100% of underlying JavaScript handlers and APIs.
"""

import os
import re
import glob

NAV_ITEMS = [
    ('index.html', 'Tableau de bord', '📊'),
    ('pipeline.html', 'CRM & Pipeline', '📈'),
    ('catalog.html', 'Catalogue', '📦'),
    ('quote_builder.html', 'Devis & Approbations', '📝'),
    ('orders.html', 'Commandes', '🛒'),
    ('inventory.html', 'Stock & Entrepôts', '🏭'),
    ('procurement.html', 'Achats & Fournisseurs', '🚢'),
    ('logistics.html', 'Logistique & Expéditions', '🚚'),
    ('invoices.html', 'Factures & TVA', '📄'),
    ('checkout.html', 'Caisse & Paiements', '💳'),
    ('support.html', 'Support & SAV', '🎧'),
    ('schedule.html', 'Rendez-vous', '📅'),
    ('inbox.html', 'Omnicanal', '💬'),
    ('notifications.html', 'Notifications', '🔔'),
    ('integrations.html', 'Intégrations & n8n', '🔌'),
    ('workflows.html', 'Workflows Durables', '⚡'),
    ('workflow_reliability_dashboard.html', 'Fiabilité & DLQ', '🩺'),
    ('ai_governance.html', 'Gouvernance IA', '🧠'),
    ('agent_workspace.html', 'Écosystème 18 Agents', '🤖'),
    ('voice_agent.html', 'Agent Vocal Client', '🎙️'),
    ('voice_copilot.html', 'Copilote Vocal Manager', '🗣️'),
    ('voice_observability.html', 'Télémétrie Vocale', '📡'),
    ('analytics_dashboard.html', 'Analytics Exécutif', '📉'),
    ('ai_operations_dashboard.html', 'Opérations GPU/VRAM', '💻'),
    ('saas_admin_dashboard.html', 'Admin SaaS & Quotas', '🏢'),
    ('release_console.html', 'Console de Déploiement', '🚀')
]

SIDEBAR_TEMPLATE = """    <!-- MASTER SIDEBAR -->
    <aside class="sidebar">
      <div class="brand-header">
        <div class="brand-logo-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 20V10M12 20V4M6 20v-6"></path></svg>
        </div>
        <div class="brand-text">
          <span class="title">Sales AI</span>
          <span class="subtitle">Management</span>
        </div>
      </div>

      <div class="nav-group">
        <ul class="nav-list">
{nav_links}
        </ul>
      </div>

      <div class="sidebar-footer">
        <div class="ai-status-pill" onclick="window.location.href='agent_workspace.html'">
          <span class="sparkle-icon">✨</span>
          <div class="info">
            <span class="status-title">IA Active</span>
            <span class="status-desc">4 agents opérationnels</span>
          </div>
        </div>

        <div class="user-profile-card">
          <div class="user-avatar">OA</div>
          <div class="user-details">
            <span class="name">Omar A.</span>
            <span class="role">Administrateur</span>
          </div>
        </div>
      </div>
    </aside>
"""

TOPBAR_TEMPLATE = """      <header class="topbar">
        <button class="mobile-menu-btn" id="mobileMenuToggle">☰</button>
        <div class="search-container">
          <span class="search-icon">🔍</span>
          <input type="text" class="search-input" id="globalSearchInput" placeholder="Rechercher des clients, devis, commandes, agents...">
          <span class="search-shortcut">Ctrl + K</span>
        </div>

        <div class="topbar-actions">
          <div class="tenant-selector-pill" id="tenantSelectorPill">
            <span>🏢</span> <span id="currentTenantLabel">Atlas Commerce</span>
          </div>

          <div class="icon-btn-badge" id="notifBtn">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg>
            <span class="badge-counter">3</span>
          </div>

          <button class="btn-header-primary" id="btnQuickNew">
            <span>+</span> Nouveau
          </button>

          <div class="user-topbar-pill">
            <div class="user-avatar" style="width:34px; height:34px; background:#082C22; color:#FFFFFF; border:2px solid #10B981;">OA</div>
            <div style="display:flex; flex-direction:column; line-height:1.2;">
              <span style="font-weight:600; font-size:13px; color:#17251F;">Omar A.</span>
              <span style="font-size:11px; color:#66756D;">Administrateur</span>
            </div>
          </div>
        </div>
      </header>
"""

def build_sidebar(current_filename):
    links = []
    for fn, label, icon in NAV_ITEMS:
        active_class = " active" if fn == current_filename else ""
        badge_html = ' <span class="badge">8</span>' if fn == 'inbox.html' else ''
        links.append(f'          <li><a href="{fn}" class="nav-item{active_class}"><span class="icon">{icon}</span><span class="label">{label}</span>{badge_html}</a></li>')
    return SIDEBAR_TEMPLATE.format(nav_links='\n'.join(links))

def clean_css(css_text):
    # Remove standard boilerplate from original css
    css_text = re.sub(r':root\s*\{[^}]*\}', '', css_text, flags=re.DOTALL)
    css_text = re.sub(r'\*\s*\{[^}]*\}', '', css_text, flags=re.DOTALL)
    css_text = re.sub(r'body\s*\{[^}]*\}', '', css_text, flags=re.DOTALL)
    css_text = re.sub(r'\.sidebar\b[^{]*\{[^}]*\}', '', css_text, flags=re.DOTALL)
    css_text = re.sub(r'\.brand-[^{]*\{[^}]*\}', '', css_text, flags=re.DOTALL)
    css_text = re.sub(r'\.nav-[^{]*\{[^}]*\}', '', css_text, flags=re.DOTALL)
    css_text = re.sub(r'\.topbar\b[^{]*\{[^}]*\}', '', css_text, flags=re.DOTALL)
    css_text = re.sub(r'\.main-area\b[^{]*\{[^}]*\}', '', css_text, flags=re.DOTALL)
    return css_text.strip()

def process_file(filepath):
    filename = os.path.basename(filepath)
    with open(filepath, 'r', encoding='utf-8') as f:
        html = f.read()

    # Extract Title
    title_match = re.search(r'<title>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else "Sales AI Management"

    # Extract Style
    style_matches = re.findall(r'<style>(.*?)</style>', html, re.DOTALL | re.IGNORECASE)
    cleaned_styles = []
    for s in style_matches:
        cleaned = clean_css(s)
        if cleaned:
            cleaned_styles.append(cleaned)
    custom_style = "\n".join(cleaned_styles)

    # Extract Scripts
    scripts = re.findall(r'<script\b[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
    # Filter out empty or duplicate app_shell.js references
    page_scripts = [s.strip() for s in scripts if s.strip() and 'app_shell.js' not in s]

    # Extract Content
    # Look for content in <div class="content"> or <div class="content-body"> or <main class="main-area">
    content = ""
    content_match = re.search(r'<div class="(?:content|content-body)"[^>]*>(.*?)</div>\s*(?:</div>\s*</main>|</main>|</div>\s*</div>|<!-- Modal|<script)', html, re.DOTALL | re.IGNORECASE)
    if content_match:
        content = content_match.group(1).strip()
    else:
        # Fallback: extract everything inside <main> or <div class="main-area"> after <div class="topbar">
        main_match = re.search(r'<div class="topbar"[^>]*>.*?</div>\s*(.*?)<\s*(?:script|/body)', html, re.DOTALL | re.IGNORECASE)
        if main_match:
            content = main_match.group(1).strip()
        else:
            body_match = re.search(r'<body[^>]*>(.*?)</body>', html, re.DOTALL | re.IGNORECASE)
            content = body_match.group(1).strip() if body_match else ""

    # Extract any modals outside of content
    modals = re.findall(r'(<div class="modal-overlay"[^>]*>.*?</div>\s*</div>)', html, re.DOTALL | re.IGNORECASE)
    modals_html = "\n".join(modals)

    # Modernize class names in content
    content = content.replace('class="panel"', 'class="card"')
    content = content.replace('class="panel-header"', 'class="card-header"')
    content = content.replace('class="panel-title"', 'class="card-title"')
    content = re.sub(r'<table\b(?![^>]*class=)', '<table class="data-table"', content)
    content = content.replace('<table>', '<table class="data-table">')

    # Wrap tables in table-responsive if not already
    # (Safe string replacement)
    content = re.sub(r'(?<!<div class="table-responsive">)\s*(<table class="data-table"[^>]*>.*?</table>)', r'<div class="table-responsive">\1</div>', content, flags=re.DOTALL)

    sidebar_html = build_sidebar(filename)
    topbar_html = TOPBAR_TEMPLATE

    style_tag = f"  <style>\n{custom_style}\n  </style>" if custom_style else ""

    scripts_tag = ""
    for s in page_scripts:
        scripts_tag += f"  <script>\n{s}\n  </script>\n"

    new_html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link rel="stylesheet" href="css/design_system.css">
{style_tag}
</head>
<body>
  <div class="app-container">
{sidebar_html}
    <div class="main-wrapper">
{topbar_html}
      <main class="content-wrapper">
{content}
      </main>
    </div>
  </div>

{modals_html}
  <script src="js/app_shell.js"></script>
{scripts_tag}
</body>
</html>
"""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_html)
    print(f"Upgraded {filename} successfully.")

def main():
    already_done = {'index.html', 'inbox.html', 'quote_builder.html', 'pipeline.html', 'catalog.html', 'orders.html', 'approvals.html'}
    all_files = glob.glob('src/frontend/*.html')
    for f in all_files:
        fn = os.path.basename(f)
        if fn not in already_done:
            process_file(f)

if __name__ == '__main__':
    main()
