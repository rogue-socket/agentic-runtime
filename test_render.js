const fs = require('fs');
const js = fs.readFileSync('docs/site/app.js', 'utf8');
const doc = fs.readFileSync('docs/site/content.js', 'utf8');

// Mock DOM
global.document = {
  getElementById: () => ({ addEventListener: () => {} }),
  querySelectorAll: () => [],
  body: { classList: { toggle: () => {}, contains: () => false } }
};
global.window = {
  addEventListener: () => {},
  innerWidth: 1000
};

try {
  eval(js);
  eval(doc);
  console.log("Scripts loaded successfully.");
} catch(e) {
  console.error("Error loading scripts:", e);
}
