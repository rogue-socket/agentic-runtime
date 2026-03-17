#!/usr/bin/env bash
set -euo pipefail

echo ""
echo "agentic-runtime onboarding"
echo "This script initializes a project, configures a provider, and runs a sample."
echo ""

read -r -p "Project directory [.]: " PROJECT_DIR
PROJECT_DIR="${PROJECT_DIR:-.}"

if [ ! -d "$PROJECT_DIR" ]; then
  echo "Directory does not exist: $PROJECT_DIR"
  exit 1
fi

if [ ! -f "$PROJECT_DIR/runtime.yaml" ]; then
  echo "Initializing project in $PROJECT_DIR"
  ai init --path "$PROJECT_DIR"
fi

echo ""
echo "Configuring provider via ai setup..."
ai setup --path "$PROJECT_DIR"

echo ""
read -r -p "Which provider did you configure? [openai/anthropic/gemini/local] (openai): " PROVIDER
PROVIDER="${PROVIDER:-openai}"

SAMPLE_PATH=""
if [ "$PROVIDER" = "gemini" ]; then
  SAMPLE_PATH="$PROJECT_DIR/workflows/samples/06_gemini_call.yaml"
elif [ "$PROVIDER" = "openai" ]; then
  SAMPLE_PATH="$PROJECT_DIR/workflows/samples/05_llm_call.yaml"
fi

if [ -n "$SAMPLE_PATH" ] && [ -f "$SAMPLE_PATH" ]; then
  read -r -p "Run sample now? [Y/n]: " RUN_SAMPLE
  RUN_SAMPLE="${RUN_SAMPLE:-Y}"
  if [ "$RUN_SAMPLE" = "Y" ] || [ "$RUN_SAMPLE" = "y" ]; then
    echo ""
    echo "Running sample: $SAMPLE_PATH"
    ai run "$SAMPLE_PATH" -i issue="Login fails with 401"
  fi
else
  echo ""
  echo "No sample workflow found for provider '$PROVIDER'."
  echo "You can run a workflow with: ai run <workflow.yaml>"
fi

echo ""
echo "Next steps:"
echo "  - Inspect a run: ai inspect <run_id> --steps"
echo "  - Visualize: ai visualize <run_id> --html"
echo ""
