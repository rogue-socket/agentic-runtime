(() => {
  const DEFAULT_DOC = "guide/getting-started.md";
  const docContent = document.getElementById("doc-content");
  const docTitle = document.getElementById("doc-title");
  const rawLink = document.getElementById("raw-link");
  const search = document.getElementById("search");
  const clear = document.getElementById("clear");
  const navItems = Array.from(document.querySelectorAll(".nav-item"));

  const escapeHtml = (value) => (
    value
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/\"/g, "&quot;")
      .replace(/'/g, "&#39;")
  );

  const formatInline = (value) => {
    let result = escapeHtml(value);
    result = result.replace(/`([^`]+)`/g, "<code>$1</code>");
    result = result.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    result = result.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    return result;
  };

  const renderMarkdown = (markdown) => {
    const lines = markdown.replace(/\r\n/g, "\n").split("\n");
    let html = "";
    let inCode = false;
    let listType = null;
    let paragraph = [];

    const flushParagraph = () => {
      if (!paragraph.length) {
        return;
      }
      html += `<p>${formatInline(paragraph.join(" "))}</p>`;
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
          html += "</code></pre>";
          inCode = false;
        } else {
          flushParagraph();
          closeList();
          const lang = line.trim().slice(3).trim();
          const langAttr = lang ? ` data-lang="${escapeHtml(lang)}"` : "";
          html += `<pre><code${langAttr}>`;
          inCode = true;
        }
        continue;
      }

      if (inCode) {
        html += `${escapeHtml(line)}\n`;
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
        html += `<h${level}>${formatInline(heading[2].trim())}</h${level}>`;
        continue;
      }

      if (line.startsWith(">")) {
        flushParagraph();
        closeList();
        const quote = line.replace(/^>\s?/, "");
        html += `<blockquote>${formatInline(quote)}</blockquote>`;
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
        html += `<li>${formatInline((ul || ol)[1].trim())}</li>`;
        continue;
      }

      paragraph.push(line.trim());
    }

    flushParagraph();
    closeList();
    if (inCode) {
      html += "</code></pre>";
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
    docContent.innerHTML = renderMarkdown(content);
    docTitle.textContent = title || docPath;
    rawLink.href = `../${docPath}`;
    setActive(docPath);
  };

  navItems.forEach((item) => {
    item.addEventListener("click", () => {
      loadDoc(item.dataset.doc, item.dataset.title);
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
})();
