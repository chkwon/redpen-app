#!/bin/bash
# Build script for Netlify
# Injects actual file contents into index.html

set -e

echo "Starting build..."

# Read file contents and escape for sed
WORKFLOW_CONTENT=$(cat .github/workflows/redpen-review.yml)
CONFIG_CONTENT=$(cat config.yml)

# Use Python for reliable text replacement (available on Netlify)
python3 << 'EOF'
import re

# Read the files
with open('.github/workflows/redpen-review.yml', 'r') as f:
    workflow = f.read()

with open('config.yml', 'r') as f:
    config = f.read()

with open('index.html', 'r') as f:
    html = f.read()

# Replace workflow content (between <pre id="code"> and </pre>)
html = re.sub(
    r'<pre id="code">.*?</pre>',
    '<pre id="code">' + workflow.rstrip() + '</pre>',
    html,
    flags=re.DOTALL
)

# Replace config content (between <pre id="config"> and </pre>)
html = re.sub(
    r'<pre id="config">.*?</pre>',
    '<pre id="config">' + config.rstrip() + '</pre>',
    html,
    flags=re.DOTALL
)

with open('index.html', 'w') as f:
    f.write(html)

print("Injected workflow and config into index.html")
EOF

echo "Build complete!"
