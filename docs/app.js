(() => {
  const DEFAULT_DOC = "guide/getting-started.md";
  const docContent = document.getElementById("doc-content");
  const docTitle = document.getElementById("doc-title");
  const rawLink = document.getElementById("raw-link");
  const search = document.getElementById("search");
  const clear = document.getElementById("clear");
  const navItems = Array.from(document.querySelectorAll(".nav-item"));
  const collapseButtons = [
    document.getElementById("collapse"),
    document.getElementById("collapse-main"),
  ].filter(Boolean);

  const setSidebarState = (open) => {
    document.body.classList.toggle("sidebar-open", open);
    document.body.classList.toggle("sidebar-collapsed", !open);
  };

  const escapeHtml = (value) => (
    value
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;")
  );

  const normalizePath = (path) => {
    const parts = [];
    path.split("/").forEach((part) => {
      if (!part || part === ".") {
        return;
      }
      if (part === "..") {
        parts.pop();
        return;
      }
      parts.push(part);
    });
    return parts.join("/");
  };

  const resolveDocPath = (currentDoc, href) => {
    if (href.startsWith("docs/")) {
      return href.slice("docs/".length);
    }
    if (href.startsWith("/")) {
      return href.replace(/^\/+/, "");
    }
    const baseDir = currentDoc.split("/").slice(0, -1).join("/");
    return normalizePath(`${baseDir}/${href}`);
  };

  const formatInline = (value, currentDoc) => {
    let result = escapeHtml(value);
    result = result.replace(/`([^`]+)`/g, "<code>$1</code>");
    result = result.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    result = result.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (match, text, href) => {
      if (!href) {
        return text;
      }
      const isExternal = /^(https?:|mailto:|#)/.test(href);
      if (href.endsWith(".md")) {
        const docPath = resolveDocPath(currentDoc, href);
        return `<a href="#" data-doc-link="${docPath}">${text}</a>`;
      }
      if (isExternal) {
        return `<a href="${href}" target="_blank" rel="noopener">${text}</a>`;
      }
      const resolved = resolveDocPath(currentDoc, href);
      return `<a href="./${resolved}" target="_blank" rel="noopener">${text}</a>`;
    });
    result = result.replace(/\[\[pill!(.*?)\]\]/g, '<span class="pill primary">$1</span>');
    result = result.replace(/\[\[i!(.*?)\]\]/g, '<span class="pill info">$1</span>');
    result = result.replace(/\[\[b!(.*?)\]\]/g, '<span class="pill warning">$1</span>');
    return result;
  };

  const highlightCode = (code, lang) => {
    let output = code;
    const placeholders = [];
    const tokenId = (index) => `__TOK_${index}__`;
    const store = (html) => {
      const id = tokenId(placeholders.length);
      placeholders.push(html);
      return id;
    };

    const protect = (pattern, cls, formatter) => {
      output = output.replace(pattern, (...args) => {
        const match = args[0];
        const text = formatter ? formatter(...args) : match;
        const html = `<span class="token ${cls}">${escapeHtml(text)}</span>`;
        return store(html);
      });
    };

    // Comments
    protect(/(^|[^\S\r\n])#.*$/gm, "comment");
    protect(/\/\/.*$/gm, "comment");

    // Strings
    protect(/"(?:[^"\\]|\\.)*"/g, "string");
    protect(/'(?:[^'\\]|\\.)*'/g, "string");

    // Numbers
    protect(/\b\d+(?:\.\d+)?\b/g, "number");

    if (lang === "yaml" || lang === "yml") {
      output = output.replace(/^(\s*)([A-Za-z0-9_.-]+)(:)/gm, (m, indent, key, colon) => {
        const html = `<span class="token key">${escapeHtml(key)}</span>`;
        return `${indent}${store(html)}${colon}`;
      });
      protect(/\b(true|false|null)\b/gi, "keyword");
    }

    if (lang === "python") {
      protect(/\b(async|await|class|def|return|if|elif|else|for|while|try|except|finally|with|as|from|import|pass|break|continue|True|False|None|and|or|not|in|is)\b/g, "keyword");
    }

    if (lang === "bash" || lang === "sh" || lang === "shell") {
      output = output.replace(/^(\s*)([A-Za-z0-9_./-]+)(\s+)/gm, (m, indent, cmd, space) => {
        const html = `<span class="token command">${escapeHtml(cmd)}</span>`;
        return `${indent}${store(html)}${space}`;
      });
      protect(/(\s--?[A-Za-z0-9_-]+)/g, "flag");
    }

    output = escapeHtml(output);
    for (let i = placeholders.length - 1; i >= 0; i--) {
      const marker = tokenId(i);
      output = output.split(marker).join(placeholders[i]);
    }

    return output;
  };

  const renderMarkdown = (markdown, currentDoc) => {
    const lines = markdown.replace(/\r\n/g, "\n").split("\n");
    let html = "";
    let inCode = false;
    let listType = null;
    let paragraph = [];
    let codeBuffer = [];
    let codeLang = "";
    let inTabs = false;
    let tabsData = null;
    let inTable = false;
    let tableBuffer = [];
    let blockquoteBuffer = [];

    const flushParagraph = () => {
      if (!paragraph.length) {
        return;
      }
      html += `<p>${formatInline(paragraph.join(" "), currentDoc)}</p>`;
      paragraph = [];
    };

    const closeList = () => {
      if (!listType) {
        return;
      }
      html += `</${listType}>`;
      listType = null;
    };

    const flushTable = () => {
      if (inTable && tableBuffer.length > 0) {
        html += `<div class="table-wrapper"><table>`;
        tableBuffer.forEach((row, idx) => {
          let cols = row.split('|').map(c => c.trim());
          if (cols[0] === '') cols.shift();
          if (cols[cols.length - 1] === '') cols.pop();
          if (idx === 0) {
            html += `<thead><tr>${cols.map(c => `<th>${formatInline(c, currentDoc)}</th>`).join('')}</tr></thead><tbody>`;
          } else if (idx === 1 && /^[-\s:]+$/.test(row.replace(/\|/g, ''))) {
            // separator
          } else {
            html += `<tr>${cols.map(c => `<td>${formatInline(c, currentDoc)}</td>`).join('')}</tr>`;
          }
        });
        html += `</tbody></table></div>`;
        inTable = false;
        tableBuffer = [];
      }
    };

    const flushBlockquote = () => {
      if (!blockquoteBuffer.length) return;
      const firstLine = blockquoteBuffer[0];
      const ghCallout = firstLine.match(/^\[!(Tip|Note|Idea|Warning|Caution)\]\s*$/i);
      const classicCallout = firstLine.match(/^(\*\*?)?(Tip|Note|Idea|Warning|Caution)\**?:?\s*(.*)$/i);
      if (ghCallout) {
        const raw = ghCallout[1];
        const label = raw.charAt(0).toUpperCase() + raw.slice(1).toLowerCase();
        const text = blockquoteBuffer.slice(1).join(" ");
        const cls = `callout callout-${label.toLowerCase()}`;
        html += `<blockquote class="${cls}"><strong>${label}:</strong> ${formatInline(text, currentDoc)}</blockquote>`;
      } else if (classicCallout) {
        const label = classicCallout[2];
        const restOfFirst = classicCallout[3] || "";
        const text = [restOfFirst, ...blockquoteBuffer.slice(1)].filter(Boolean).join(" ");
        const cls = `callout callout-${label.toLowerCase()}`;
        html += `<blockquote class="${cls}"><strong>${label}:</strong> ${formatInline(text, currentDoc)}</blockquote>`;
      } else {
        const text = blockquoteBuffer.join(" ");
        html += `<blockquote class="callout callout-note">${formatInline(text, currentDoc)}</blockquote>`;
      }
      blockquoteBuffer = [];
    };

    const flushAll = () => {
      flushParagraph();
      closeList();
      flushTable();
      flushBlockquote();
    };

    for (const line of lines) {
      if (inTabs) {
        if (line.trim() === "::::") {
          inTabs = false;
          let tabsHtml = `<div class="tabs-container"><div class="tabs-header">`;
          tabsData.tabs.forEach((tab, index) => {
            tabsHtml += `<button class="tab-button ${index === 0 ? 'active' : ''}" data-tab-id="${index}">${formatInline(tab.name, currentDoc)}</button>`;
          });
          tabsHtml += `</div><div class="tabs-content">`;
          tabsData.tabs.forEach((tab, index) => {
            const tabContentHtml = renderMarkdown(tab.contentLines.join("\n"), currentDoc);
            tabsHtml += `<div class="tab-pane ${index === 0 ? 'active' : ''}" data-tab-id="${index}">${tabContentHtml}</div>`;
          });
          tabsHtml += `</div></div>`;
          html += tabsHtml;
          tabsData = null;
          continue;
        }
        if (line.trim().startsWith(":::tab ")) {
          tabsData.tabs.push({ name: line.trim().slice(":::tab ".length).trim(), contentLines: [] });
          continue;
        }
        if (tabsData.tabs.length > 0) {
          tabsData.tabs[tabsData.tabs.length - 1].contentLines.push(line);
        }
        continue;
      }

      if (line.trim() === "::::tabs") {
        flushAll();
        inTabs = true;
        tabsData = { tabs: [] };
        continue;
      }

      if (line.trim().startsWith("|") && line.trim().endsWith("|")) {
        flushParagraph();
        closeList();
        inTable = true;
        tableBuffer.push(line.trim());
        continue;
      } else if (inTable) {
        flushTable();
      }

      if (line.trim().startsWith("```")) {
        if (inCode) {
          const rawCode = codeBuffer.join("\n");
          const lang = codeLang || "text";
          if (lang === "mermaid") {
            html += `<div class="mermaid-container" data-mermaid="${escapeHtml(rawCode)}"></div>`;
          } else {
            const highlighted = highlightCode(rawCode, codeLang);
            html += `<div class="code-shell">` +
                    `<div class="code-head"><span class="code-lang">${escapeHtml(lang)}</span></div>` +
                    `<pre><code class="lang-${escapeHtml(lang)}">${highlighted}</code></pre>` +
                    `</div>`;
          }
          inCode = false;
          codeBuffer = [];
          codeLang = "";
        } else {
          flushAll();
          codeLang = line.trim().slice(3).trim();
          inCode = true;
        }
        continue;
      }

      if (inCode) {
        codeBuffer.push(line);
        continue;
      }

      if (!line.trim()) {
        flushAll();
        continue;
      }

      const heading = line.match(/^(#{1,3})\s+(.*)$/);
      if (heading) {
        flushAll();
        const level = heading[1].length;
        html += `<h${level}>${formatInline(heading[2].trim(), currentDoc)}</h${level}>`;
        continue;
      }

      if (/^-{3,}$/.test(line.trim()) || /^\*{3,}$/.test(line.trim()) || /^_{3,}$/.test(line.trim())) {
        flushAll();
        html += `<hr />`;
        continue;
      }

      if (line.startsWith(">")) {
        flushParagraph();
        closeList();
        flushTable();
        const quote = line.replace(/^>\s?/, "");
        blockquoteBuffer.push(quote);
        continue;
      }
      if (blockquoteBuffer.length) {
        flushBlockquote();
      }

      const ul = line.match(/^\s*[-*]\s+(.*)$/);
      const ol = line.match(/^\s*\d+\.\s+(.*)$/);
      if (ul || ol) {
        flushParagraph();
        const nextType = ul ? "ul" : "ol";
        if (listType && listType !== nextType) {
          closeList();
        }
        if (!listType) {
          html += `<${nextType}>`;
          listType = nextType;
        }
        html += `<li>${formatInline((ul || ol)[1].trim(), currentDoc)}</li>`;
        continue;
      }

      paragraph.push(line.trim());
    }

    flushAll();
    if (inCode) {
      const rawCode = codeBuffer.join("\n");
      const lang = codeLang || "text";
      const highlighted = highlightCode(rawCode, codeLang);
      html += `<div class="code-shell">` +
              `<div class="code-head"><span class="code-lang">${escapeHtml(lang)}</span></div>` +
              `<pre><code class="lang-${escapeHtml(lang)}">${highlighted}</code></pre>` +
              `</div>`;
    }

    return html;
  };

  const setActive = (docPath) => {
    navItems.forEach((item) => {
      item.classList.toggle("active", item.dataset.doc === docPath);
    });
  };

  const loadDoc = (docPath, title) => {
    const content = window.DOCS && window.DOCS[docPath];
    if (!content) {
      docContent.innerHTML = `<p>Unable to find <code>${docPath}</code> in the doc index.</p>`;
      docTitle.textContent = title || "Document";
      rawLink.href = `./${docPath}`;
      setActive(docPath);
      return;
    }
    docContent.innerHTML = renderMarkdown(content, docPath);
    
    if (window.mermaid) {
      docContent.querySelectorAll('.mermaid-container').forEach((el, index) => {
        const code = el.getAttribute('data-mermaid');
        const id = `mermaid-svg-${Date.now()}-${index}`;
        mermaid.render(id, code)
          .then(({ svg }) => { el.innerHTML = svg; })
          .catch(e => {
            console.error("Mermaid render failed", e);
            el.innerHTML = `<pre class="code-shell">${escapeHtml(code)}</pre>`;
          });
      });
    }

    docTitle.textContent = title || docPath;
    rawLink.href = `./${docPath}`;
    setActive(docPath);
    docContent.querySelectorAll("[data-doc-link]").forEach((link) => {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        const target = link.getAttribute("data-doc-link");
        if (target) {
          const navItem = navItems.find((item) => item.dataset.doc === target);
          loadDoc(target, navItem ? navItem.dataset.title : target);
        }
      });
    });

    docContent.querySelectorAll(".tabs-container").forEach((container) => {
      const buttons = container.querySelectorAll(".tab-button");
      const panes = container.querySelectorAll(".tab-pane");
      buttons.forEach(btn => {
        btn.addEventListener("click", () => {
          const tabId = btn.getAttribute("data-tab-id");
          buttons.forEach(b => b.classList.toggle("active", b === btn));
          panes.forEach(p => p.classList.toggle("active", p.getAttribute("data-tab-id") === tabId));
        });
      });
    });
  };

  navItems.forEach((item) => {
    const tip = item.dataset.title || item.dataset.doc || "Open doc";
    item.setAttribute("data-tip", tip);
    item.addEventListener("click", () => {
      loadDoc(item.dataset.doc, item.dataset.title);
      if (window.innerWidth <= 960) {
        setSidebarState(false);
      }
    });
  });

  const filterNav = () => {
    const term = search.value.trim().toLowerCase();
    navItems.forEach((item) => {
      const title = (item.dataset.title || "").toLowerCase();
      const doc = (item.dataset.doc || "").toLowerCase();
      item.style.display = (title.includes(term) || doc.includes(term)) ? "block" : "none";
    });
  };

  search.addEventListener("input", filterNav);
  clear.addEventListener("click", () => {
    search.value = "";
    filterNav();
  });

  const initialItem = navItems.find((item) => item.dataset.doc === DEFAULT_DOC) || navItems[0];
  if (initialItem) {
    loadDoc(initialItem.dataset.doc, initialItem.dataset.title);
  }

  const shouldOpen = window.innerWidth > 960;
  setSidebarState(shouldOpen);

  collapseButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const open = document.body.classList.contains("sidebar-open");
      setSidebarState(!open);
    });
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 960) {
      setSidebarState(true);
    } else if (!document.body.classList.contains("sidebar-open")) {
      setSidebarState(false);
    }
  });
})();
