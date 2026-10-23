"""Run Jev filtering on an existing MediaCrawler Excel search export."""

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

from semantic_filter import filter_workbook, filter_checkpoint, SUPPORTED_MODELS, MODEL


def main() -> None:
    parser = argparse.ArgumentParser(description="Review saved Excel or checkpoint candidates with current scene rules")
    parser.add_argument("--file", type=Path, required=True, help="Raw Excel export or semantic checkpoint .jsonl (includes old rejections)")
    parser.add_argument("--first", required=True, help="Keyword 1, e.g. 可爱")
    parser.add_argument("--second", required=True, help="Keyword 2, e.g. 公园")
    parser.add_argument("--model", choices=SUPPORTED_MODELS, default=MODEL)
    parser.add_argument("--output-dir", type=Path, help="Separate directory for the new workbook and checkpoints")
    args = parser.parse_args()
    if not args.file.is_file() or args.file.suffix.lower() not in {".xlsx", ".jsonl"}:
        parser.error("--file must point to an existing .xlsx or .jsonl file")
    api_key = os.environ.get("TYPESAFE_API_KEY")
    if args.model == MODEL and not api_key and sys.stdin.isatty():
        api_key = getpass.getpass("TypeSafe API Key: ")
    if args.model == MODEL and not api_key:
        parser.error("TYPESAFE_API_KEY is not set and no key was entered")
    review = filter_checkpoint if args.file.suffix.lower() == ".jsonl" else filter_workbook
    output, counts = asyncio.run(review(args.file, [(args.first, args.second)], api_key or "", model=args.model, output_dir=args.output_dir))
    print(f"Saved {output}; matched={counts['matched']}, review={counts['review']}, "
          f"excluded={counts['excluded']}, duplicate={counts['duplicate']}, pending={counts['pending']}, API calls={counts['api_calls']}")


if __name__ == "__main__":
    main()
