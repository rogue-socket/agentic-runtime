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
      return `<a href="../${resolved}" target="_blank" rel="noopener">${text}</a>`;
    });
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
    placeholders.forEach((html, index) => {
      const marker = tokenId(index);
      output = output.split(marker).join(html);
    });

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

    for (const line of lines) {
      if (line.trim().startsWith("```")) {
        if (inCode) {
          const rawCode = codeBuffer.join("\n");
          const lang = codeLang || "text";
          const highlighted = highlightCode(rawCode, codeLang);
          html += `<div class="code-shell">` +
                  `<div class="code-head"><span class="code-lang">${escapeHtml(lang)}</span></div>` +
                  `<pre><code class="lang-${escapeHtml(lang)}">${highlighted}</code></pre>` +
                  `</div>`;
          inCode = false;
          codeBuffer = [];
          codeLang = "";
        } else {
          flushParagraph();
          closeList();
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
        flushParagraph();
        closeList();
        continue;
      }

      const heading = line.match(/^(#{1,3})\s+(.*)$/);
      if (heading) {
        flushParagraph();
        closeList();
        const level = heading[1].length;
        html += `<h${level}>${formatInline(heading[2].trim(), currentDoc)}</h${level}>`;
        continue;
      }

      if (line.startsWith(">")) {
        flushParagraph();
        closeList();
        const quote = line.replace(/^>\s?/, "");
        const calloutMatch = quote.match(/^(\\*\\*)?(Tip|Note|Idea|Warning|Caution)\\*\\*?:\\s*(.*)$/i);
        if (calloutMatch) {
          const label = calloutMatch[2];
          const text = calloutMatch[3] || "";
          const cls = `callout callout-${label.toLowerCase()}`;
          html += `<blockquote class="${cls}"><strong>${label}:</strong> ${formatInline(text, currentDoc)}</blockquote>`;
        } else {
          html += `<blockquote class="callout callout-note">${formatInline(quote, currentDoc)}</blockquote>`;
        }
        continue;
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

    flushParagraph();
    closeList();
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
      rawLink.href = `../${docPath}`;
      setActive(docPath);
      return;
    }
    docContent.innerHTML = renderMarkdown(content, docPath);
    docTitle.textContent = title || docPath;
    rawLink.href = `../${docPath}`;
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
