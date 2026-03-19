**Docs UI**

Open `docs/site/index.html` in a browser to browse the documentation with search and in-page rendering.

If you prefer a local server (optional):

```bash
cd /Users/yashagrawal/Documents/agentic-runtime/docs/site
python -m http.server
```

Then open `http://localhost:8000` in your browser.

**Updating the Index**

If you edit or add docs, rebuild the index so the UI can see them:

```bash
python /Users/yashagrawal/Documents/agentic-runtime/docs/site/build-content.py
```
