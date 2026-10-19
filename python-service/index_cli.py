"""Small command-line entry points for standalone indexing and retrieval."""

import argparse
import json

from indexing import index_repository, search_repository


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    index = commands.add_parser("index", help="Index a local repository revision")
    index.add_argument("--repo-id", required=True)
    index.add_argument("--path", required=True)
    index.add_argument("--revision", required=True, help="Git commit SHA or immutable revision key")

    search = commands.add_parser("search", help="Search the active repository index")
    search.add_argument("--repo-id", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=5)

    args = parser.parse_args()
    if args.command == "index":
        result = index_repository(args.repo_id, args.path, args.revision)
    else:
        result = search_repository(args.repo_id, args.query, limit=args.limit)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
