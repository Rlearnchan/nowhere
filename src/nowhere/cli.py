from __future__ import annotations

import argparse
from pathlib import Path

TEMPLATE = """# {date} 시황 라이브 참고 자료

- 제목: {title}
- 작성 상태: draft
- 확인 기준 시각(KST): 

## 오늘의 핵심 흐름

- 

## 꼭 확인할 지표

| 항목 | 수치/상태 | 출처 | 메모 |
|---|---:|---|---|

## 링크 큐

| 상태 | 제목 | URL | 사용 메모 |
|---|---|---|---|

## 방송용 포인트

1. 

## 리스크/확인 필요

- 
"""


def init_day(root: Path, date: str, title: str) -> Path:
    day_dir = root / "references" / date
    day_dir.mkdir(parents=True, exist_ok=True)
    for name in ("links.md", "market_brief.md", "talking_points.md", "source_notes.md"):
        path = day_dir / name
        if not path.exists():
            path.write_text(f"# {date} {name}\n\n", encoding="utf-8")
    readme = day_dir / "README.md"
    if not readme.exists():
        readme.write_text(TEMPLATE.format(date=date, title=title), encoding="utf-8")
    return day_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nowhere")
    subparsers = parser.add_subparsers(dest="command")
    init = subparsers.add_parser("init-day", help="Create a daily live reference folder")
    init.add_argument("--root", type=Path, default=Path.cwd())
    init.add_argument("--date", required=True)
    init.add_argument("--title", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "init-day":
        print(init_day(args.root, args.date, args.title))
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
