#!/usr/bin/env python3
"""Shopping agent example using ForrestRun RuntimeBuilder.

This example demonstrates:
  - ReAct agent strategy with tool use
  - Multi-step workflow with agent and tool steps
  - Custom tool registration
  - RuntimeBuilder for flexible configuration

Prerequisites:
  - OPENAI_API_KEY environment variable set
  - ForrestRun installed: pip install -e ../..

Usage:
  python run.py
  python run.py --shopping-list "Buy a laptop under 1500 dollars"
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path so we can import from the installed forrestrun
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from forrestrun import RuntimeBuilder
from tools.shop_tools import (
    ShopListProductsTool,
    ShopGetProductTool,
    ShopCreateCartTool,
    ShopAddToCartTool,
    ShopCheckoutTool,
)


def main():
    parser = argparse.ArgumentParser(description="Shopping agent example")
    parser.add_argument(
        "--shopping-list",
        default="Buy a good book and a pen, staying under 30 dollars",
        help="What to shop for",
    )
    args = parser.parse_args()

    # Create runtime with shop tools
    runtime = (
        RuntimeBuilder()
        .with_config_path("runtime.yaml")
        .with_db_path(":memory:")  # Use in-memory DB for examples
        .with_tool(ShopListProductsTool())
        .with_tool(ShopGetProductTool())
        .with_tool(ShopCreateCartTool())
        .with_tool(ShopAddToCartTool())
        .with_tool(ShopCheckoutTool())
        .build()
    )

    with runtime:
        print("🛒 ForrestRun Shopping Agent Example")
        print(f"Shopping request: {args.shopping_list}\n")

        run = runtime.run(
            "workflow.yaml",
            inputs={"shopping_list": args.shopping_list},
        )

        print(f"\n✓ Workflow completed with status: {run.status}")
        print(f"Run ID: {run.run_id}\n")

        if run.succeeded:
            print("Step results:")
            for step_id in run.step_names:
                output = run.get_output(step_id)
                if output:
                    print(f"  {step_id}:")
                    if isinstance(output, dict):
                        for key, val in output.items():
                            print(f"    {key}: {val}")
                    else:
                        print(f"    {output}")
        else:
            print(f"Workflow failed: {run.error}")


if __name__ == "__main__":
    main()
